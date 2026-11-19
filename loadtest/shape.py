"""The staged ramp: more and more virtual candidates, each step held for a while, until the system breaks (or the cap is reached, or the PC must be protected).

A step has BROKEN when, for two checks in a row (30 s windows) after it has settled, any of these hold:
  - more than 1 % of the requests failed,
  - the 95th-percentile time of answer saving, the clock or the exam state is above 2 s,
  - the server health check fails, or a container was restarted or killed for memory (when the host monitor reports it).
Separately the run STOPS TO PROTECT THE PC when free memory falls under LT_MIN_FREE_MB (the office PC also runs another application).

LT_STEPS (default 25,50,100,200,400,800,1200,1500)  LT_HOLD seconds per step (240)  LT_RAMP seconds to reach a step (60)
LT_OUT folder for steps.csv and outcome.json   LT_STATUS_URL the host monitor's /status address (empty: the local computer is watched)
LT_MIN_FREE_MB 400 (host) or 1500 (this computer)"""
import csv
import json
import os
import time
import urllib.request

import psutil
from locust import LoadTestShape

STEPS = [int(x) for x in os.environ.get("LT_STEPS", "25,50,100,200,400,800,1200,1500").split(",") if x.strip()]
HOLD = int(os.environ.get("LT_HOLD", "240"))
RAMP = int(os.environ.get("LT_RAMP", "60"))
SETTLE = 45        # seconds into a step before it is judged
WINDOW = 30
STATUS_URL = os.environ.get("LT_STATUS_URL", "")
MIN_FREE_MB = int(os.environ.get("LT_MIN_FREE_MB", "400" if STATUS_URL else "1500"))
OUT = os.environ.get("LT_OUT", "")
CRITICAL = ("save answer", "clock", "exam state")
MAX_P95_MS, MAX_FAIL_PCT = 2000, 1.0


def probe() -> dict:
    """The state of the machine that runs the server: from the host monitor, or from this computer."""
    if STATUS_URL:
        try:
            with urllib.request.urlopen(STATUS_URL, timeout=3) as r:
                return json.loads(r.read())
        except Exception as e:  # the monitor itself is not reachable: that is not a verdict on the server
            return {"monitor_error": str(e)[:80]}
    base = os.environ.get("LT_HOST", "http://127.0.0.1:8001")
    try:
        urllib.request.urlopen(base + "/api/health", timeout=3)
        ok = True
    except Exception:
        ok = False
    return {"free_mb": int(psutil.virtual_memory().available / 2 ** 20), "api_ok": ok, "restarts_total": 0, "oom": False}


class StagesShape(LoadTestShape):
    def __init__(self):
        super().__init__()
        self.i = 0
        self.t_step = None
        self.window_start = None
        self.bad = 0
        self.prev = 0
        self.log = []
        self.outcome = None
        self.last_probe = 0
        self.state = {}
        self.base_restarts = None
        self.peak = {"rps": 0, "p95": 0}

    # ---- bookkeeping
    def _write(self):
        if not OUT:
            return
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "steps.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["step", "users", "started", "ended", "result", "reason", "rps", "fail_pct", "p95_ms"])
            w.writeheader()
            w.writerows(self.log)
        with open(os.path.join(OUT, "outcome.json"), "w", encoding="utf-8") as f:
            json.dump(self.outcome or {"result": "running"}, f, indent=2)

    def _window(self):
        st = self.runner.environment.stats
        tot = st.total
        p95 = [e.get_current_response_time_percentile(0.95) or 0 for (n, _), e in st.entries.items() if n in CRITICAL]
        return {"req": tot.num_requests, "fail": tot.num_failures, "p95": max(p95) if p95 else 0, "rps": tot.current_rps}

    def _finish(self, result, reason):
        w = self._window()
        self.log.append({"step": self.i + 1, "users": STEPS[self.i], "started": round(self.t_step, 1), "ended": round(time.time(), 1), "result": result, "reason": reason,
                         "rps": round(self.peak["rps"], 1), "fail_pct": round(self.fail_pct_now(), 2), "p95_ms": round(self.peak["p95"])})
        self.outcome = {"result": result, "reason": reason, "step": self.i + 1, "users": STEPS[self.i],
                        "last_healthy_users": max([r["users"] for r in self.log if r["result"] == "ok"] or [0]), "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self._write()

    def fail_pct_now(self):
        return 100.0 * (self.win_fail / self.win_req) if getattr(self, "win_req", 0) else 0.0

    # ---- the verdict of one 30 s window
    def judge(self):
        now = self._window()
        dreq, dfail = now["req"] - self.window_start["req"], now["fail"] - self.window_start["fail"]
        self.win_req, self.win_fail = dreq, dfail
        self.peak["rps"] = max(self.peak["rps"], now["rps"])
        self.peak["p95"] = max(self.peak["p95"], now["p95"])
        reasons = []
        if dreq >= 50 and 100.0 * dfail / dreq > MAX_FAIL_PCT:
            reasons.append(f"{100.0 * dfail / dreq:.1f}% of requests failed")
        if now["p95"] > MAX_P95_MS:
            reasons.append(f"95th percentile {now['p95'] / 1000:.1f} s (answer save / clock / exam state)")
        s = self.state
        if s.get("api_ok") is False:
            reasons.append("the health check failed")
        if s.get("oom"):
            reasons.append("a container was killed for memory")
        if self.base_restarts is not None and s.get("restarts_total", 0) > self.base_restarts:
            reasons.append("a container restarted")
        self.window_start = now
        return reasons

    def tick(self):
        now = time.time()
        if self.outcome and self.outcome["result"] != "running":
            return None
        if self.t_step is None:
            self.t_step, self.window_start, self.win_time = now, self._window(), now
        if now - self.last_probe >= 5:
            self.last_probe, self.state = now, probe()
            if self.base_restarts is None and "restarts_total" in self.state:
                self.base_restarts = self.state["restarts_total"]
        free = self.state.get("free_mb")
        if free is not None and free < MIN_FREE_MB:
            self._finish("protected", f"free memory fell to {free} MB (limit {MIN_FREE_MB} MB): stopped to protect the computer")
            return None
        into = now - self.t_step
        if now - self.win_time >= WINDOW:  # a window is judged only once the step has settled
            reasons = self.judge()
            self.win_time = now
            if into >= SETTLE:
                self.bad = self.bad + 1 if reasons else 0
                if self.bad >= 2:
                    self._finish("broke", "; ".join(reasons))
                    return None
        if into >= RAMP + HOLD:
            self._finish("ok", "held the whole step")
            self.prev = STEPS[self.i]
            self.i += 1
            if self.i >= len(STEPS):
                self.outcome = {"result": "cap", "reason": "reached the highest step without breaking", "users": STEPS[-1], "last_healthy_users": STEPS[-1], "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}
                self._write()
                return None
            self.t_step, self.window_start, self.bad, self.win_time = now, self._window(), 0, now
            self.peak = {"rps": 0, "p95": 0}
            self.outcome = None
        target = STEPS[self.i]
        return target, max(1.0, abs(target - self.prev) / max(RAMP, 1))
