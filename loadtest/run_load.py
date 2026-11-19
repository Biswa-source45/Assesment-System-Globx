"""Starts one load-test scenario: Locust (a master and several workers, since Windows cannot fork), a sampler that records how the server's machine copes
every 2 seconds, and the files for the report. Run it with the load-test Python (loadtest\\.venv).

  python run_load.py ramp   --run LT-xxxx --label local-ramp  [--steps 25,50,100] [--hold 240] [--staff 5]
  python run_load.py login  --run LT-xxxx --users 100 --spawn-rate 5
  python run_load.py start|submit|code --users 100 --spawn-rate 10
  python run_load.py big    --users 5 --time 3m
  python run_load.py smoke  --users 5 --time 1m

Where: --host http://127.0.0.1:8001 (default: the host saved by setup_data.py)   --status-url http://<office PC>:9100/status/<token>  (the host monitor)
The result files land in results/<run>/<label>/ (stats CSV, report.html, steps.csv, outcome.json, metrics.jsonl)."""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import psutil

from common import RESULTS, load_run

HERE = Path(__file__).resolve().parent
CLASSES = {"ramp": ["Steady", "Staff"], "soak": ["Steady", "Staff"], "login": ["LoginStorm"], "start": ["StartStorm"], "submit": ["SubmitStorm"],
           "code": ["CodeBurst"], "big": ["BigReader"], "smoke": ["Steady", "Staff"]}


def sample_loop(stop, out_path, status_url, server_pid):
    """Every 2 s: the machine of the server (from the host monitor, or from this computer) and this generator's own load."""
    psutil.cpu_percent(interval=None)
    server = psutil.Process(server_pid) if server_pid else None
    known = {}   # cpu_percent needs the same Process object from one sample to the next
    with open(out_path, "w", encoding="utf-8") as f:
        while not stop.is_set():
            row = {"t": round(time.time(), 1), "generator_cpu": psutil.cpu_percent(interval=None), "generator_free_mb": int(psutil.virtual_memory().available / 2 ** 20)}
            if status_url:
                try:
                    with urllib.request.urlopen(status_url, timeout=3) as r:
                        row["host"] = json.loads(r.read())
                except Exception as e:
                    row["host_error"] = str(e)[:60]
            else:
                row["host"] = {"free_mb": row["generator_free_mb"]}
                if server:
                    try:
                        procs = [server] + server.children(recursive=True)   # the launcher and the real server process
                        for p in procs:
                            known.setdefault(p.pid, p)
                        mine = [known[p.pid] for p in procs]
                        row["server"] = {"cpu": round(sum(p.cpu_percent(interval=None) for p in mine), 1), "rss_mb": int(sum(p.memory_info().rss for p in mine) / 2 ** 20),
                                         "threads": sum(p.num_threads() for p in mine), "processes": len(mine)}
                        pg = [p for p in psutil.process_iter(["name", "memory_info"]) if (p.info["name"] or "").lower().startswith("postgres")]
                        row["postgres"] = {"rss_mb": int(sum(p.info["memory_info"].rss for p in pg) / 2 ** 20), "processes": len(pg)}
                    except psutil.Error:
                        pass
            f.write(json.dumps(row) + "\n")
            f.flush()
            stop.wait(2)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("scenario", choices=sorted(CLASSES))
    p.add_argument("--run", default="")
    p.add_argument("--label", default="")
    p.add_argument("--host", default="")
    p.add_argument("--insecure", action="store_true")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--users", type=int, default=10)
    p.add_argument("--spawn-rate", type=float, default=5)
    p.add_argument("--time", default="")
    p.add_argument("--steps", default="")
    p.add_argument("--hold", type=int, default=240)
    p.add_argument("--ramp", type=int, default=60)
    p.add_argument("--staff", type=int, default=0)
    p.add_argument("--status-url", default="")
    p.add_argument("--static", default="1")
    p.add_argument("--offset", type=int, default=0, help="skip this many candidate logins (used by an earlier scenario)")
    args = p.parse_args()

    run = load_run(args.run)
    label = args.label or f"{args.scenario}-{time.strftime('%H%M')}"
    out = RESULTS / run["run_id"] / label
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "LT_RUN": run["run_id"], "LT_HOST": args.host or run["host"], "LT_WORKERS": str(args.workers), "LT_OUT": str(out),
           "LT_STAFF": str(args.staff), "LT_STATIC": args.static, "LT_OFFSET": str(args.offset), "LT_STATUS_URL": args.status_url, "PYTHONUNBUFFERED": "1"}
    if args.insecure:
        env["LT_INSECURE"] = "1"
    shaped = args.scenario in ("ramp", "soak")
    if shaped:
        env["LT_SHAPE"] = "stages"
        env["LT_HOLD"], env["LT_RAMP"] = str(args.hold), str(args.ramp)
        if args.steps:
            env["LT_STEPS"] = args.steps
    if args.scenario in ("login", "start", "submit", "code"):
        env["LT_BARRIER"] = str(time.time() + args.users / max(args.spawn_rate, 0.1) + 20)
    if args.scenario == "submit":
        env["LT_SUBMIT_ON_STOP"] = "0"

    locust = [sys.executable, "-m", "locust", "-f", str(HERE / "locustfile.py")]
    workers = [subprocess.Popen(locust + ["--worker", "--master-host", "127.0.0.1"], env=env, cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
               for _ in range(args.workers)]
    master = locust + ["--master", "--headless", "--expect-workers", str(args.workers), "--csv", str(out / "stats"), "--csv-full-history",
                       "--html", str(out / "report.html"), "--only-summary"] + CLASSES[args.scenario]
    if not shaped:
        master += ["-u", str(args.users), "-r", str(args.spawn_rate)]
        if args.time:
            master += ["-t", args.time]
        elif args.scenario in ("login",):
            master += ["-t", f"{int(args.users / max(args.spawn_rate, 0.1)) + 60}s"]
        else:
            master += ["-t", f"{int(args.users / max(args.spawn_rate, 0.1)) + 150}s"]
    server_pid = None
    state = RESULTS / "local_server.json"
    if not args.status_url and state.exists():
        server_pid = json.loads(state.read_text(encoding="utf-8")).get("pid")
    stop = threading.Event()
    sampler = threading.Thread(target=sample_loop, args=(stop, out / "metrics.jsonl", args.status_url, server_pid), daemon=True)
    sampler.start()
    t0 = time.time()
    (out / "meta.json").write_text(json.dumps({"scenario": args.scenario, "label": label, "run": run["run_id"], "host": env["LT_HOST"], "started": t0, "users": args.users,
                                               "steps": env.get("LT_STEPS", ""), "hold": args.hold, "ramp": args.ramp, "workers": args.workers, "staff": args.staff,
                                               "static": args.static, "barrier": env.get("LT_BARRIER", "")}), encoding="utf-8")
    print(f"{args.scenario} on {env['LT_HOST']} -> {out}", flush=True)
    try:
        subprocess.run(master, env=env, cwd=HERE)
    finally:
        stop.set()
        for w in workers:
            w.terminate()
        (out / "meta.json").write_text(json.dumps({**json.loads((out / "meta.json").read_text(encoding="utf-8")), "ended": time.time()}), encoding="utf-8")
    log = RESULTS / "local_server.log"
    if not args.status_url and log.exists():   # what the local server complained about during this run
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        errors = {}
        for ln in lines:
            if "Error" in ln and not ln.startswith(" ") and "HTTP/1.1" not in ln:
                key = ln.strip()[:160]
                errors[key] = errors.get(key, 0) + 1
        (out / "server_log_summary.json").write_text(json.dumps({"pool_timeouts": sum(1 for ln in lines if "QueuePool limit" in ln and "TimeoutError" in ln and ln.lstrip().startswith("sqlalchemy.exc")),
                                                                  "tracebacks": sum(1 for ln in lines if ln.startswith("Traceback")), "common_errors": sorted(errors.items(), key=lambda kv: -kv[1])[:5]}, indent=2), encoding="utf-8")
    print(f"finished in {time.time() - t0:.0f} s; files in {out}", flush=True)


if __name__ == "__main__":
    main()
