"""Builds the PDF report from the files the load tests left (results/<run>/<label>/...). Run it with the load-test Python:

  python report.py --env "This computer (local test copy)" --run LT-local-xxxx [--env "Office PC" --run LT-office-xxxx ...] --out reports/load-test-report.pdf

Each --env/--run pair is one chapter. A chapter shows the staged ramp (how many candidates it carried and what broke first), the storms (everybody signs in / starts /
submits / runs code together), the large-data reads, the soak, the internet path, the cleanup proof and the screenshots found in results/<run>/screens/."""
import argparse
import csv
import json
import statistics
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
BLUE = colors.HexColor("#1d4ed8")
GREY = colors.HexColor("#64748b")
ST = getSampleStyleSheet()
H1 = ParagraphStyle("h1", parent=ST["Heading1"], textColor=BLUE, fontSize=18, spaceAfter=6)
H2 = ParagraphStyle("h2", parent=ST["Heading2"], textColor=BLUE, fontSize=13, spaceBefore=10, spaceAfter=4)
P = ParagraphStyle("p", parent=ST["BodyText"], fontSize=9.5, leading=13)
SM = ParagraphStyle("sm", parent=P, fontSize=8, leading=10, textColor=GREY)
CELL = ParagraphStyle("cell", parent=P, fontSize=7.5, leading=9)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def rows_of(path):
    p = Path(path)
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []


def jload(path, default=None):
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def table(data, widths=None, head=True, font=7.5):
    t = Table([[Paragraph(str(c), CELL) if isinstance(c, str) and len(c) > 28 else c for c in r] for r in data], colWidths=widths, repeatRows=1 if head else 0)
    style = [("FONTSIZE", (0, 0), (-1, -1), font), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")])]
    if head:
        style += [("BACKGROUND", (0, 0), (-1, 0), BLUE), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    t.setStyle(TableStyle(style))
    return t


def fig_image(fig, path, width=175 * mm):
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    from PIL import Image as PI
    w, h = PI.open(path).size
    return Image(str(path), width=width, height=width * h / w)


# ---------------------------------------------------------------- one experiment (one folder)
class Exp:
    def __init__(self, folder: Path):
        self.dir = folder
        self.meta = jload(folder / "meta.json", {})
        self.stats = rows_of(folder / "stats_stats.csv")
        self.history = [r for r in rows_of(folder / "stats_stats_history.csv") if r.get("Name") == "Aggregated"]
        self.hist_all = rows_of(folder / "stats_stats_history.csv")
        self.steps = rows_of(folder / "steps.csv")
        self.outcome = jload(folder / "outcome.json", {})
        self.metrics = [json.loads(line) for line in (folder / "metrics.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()] if (folder / "metrics.jsonl").exists() else []
        self.t0 = self.meta.get("started") or (num(self.history[0]["Timestamp"]) if self.history else 0)

    @property
    def scenario(self):
        return self.meta.get("scenario", "")

    def agg(self):
        return next((r for r in self.stats if r["Name"] == "Aggregated"), {})

    def endpoint(self, name):
        return next((r for r in self.stats if r["Name"] == name), {})


def min_of(ts, t0):
    return (ts - t0) / 60.0


def ramp_figure(exp: Exp, out: Path):
    h = exp.history
    if not h:
        return None
    xs = [min_of(num(r["Timestamp"]), exp.t0) for r in h]
    fig, ax = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
    ax[0].plot(xs, [num(r["User Count"]) or 0 for r in h], color="#1d4ed8", label="virtual candidates")
    ax[0].set_ylabel("candidates")
    ax0b = ax[0].twinx()
    ax0b.plot(xs, [num(r["Requests/s"]) or 0 for r in h], color="#16a34a", label="requests per second")
    ax0b.set_ylabel("requests / s")
    ax[1].plot(xs, [num(r["50%"]) for r in h], color="#0ea5e9", label="median")
    ax[1].plot(xs, [num(r["95%"]) for r in h], color="#f59e0b", label="95th percentile")
    ax[1].plot(xs, [num(r["99%"]) for r in h], color="#dc2626", label="99th percentile")
    ax[1].axhline(2000, color="#94a3b8", ls="--", lw=0.8)
    ax[1].set_ylabel("response time (ms)")
    ax[1].legend(loc="upper left", fontsize=7)
    ax[2].plot(xs, [num(r["Failures/s"]) or 0 for r in h], color="#dc2626")
    ax[2].set_ylabel("failures / s")
    ax[2].set_ylim(bottom=0)
    ax[2].set_xlabel("minutes since the start")
    for s in exp.steps:
        for a in ax:
            a.axvline(min_of(num(s["started"]), exp.t0), color="#cbd5e1", lw=0.8)
        ax[0].text(min_of(num(s["started"]), exp.t0), ax[0].get_ylim()[1], f" {s['users']}", fontsize=6, va="top", color="#64748b")
    for a in ax:
        a.grid(alpha=0.25)
    fig.suptitle(f"{exp.meta.get('label', '')}: candidates, speed and errors over time (steps marked)", fontsize=9)
    return fig_image(fig, out)


def resource_figure(exp: Exp, out: Path):
    m = exp.metrics
    if not m:
        return None
    xs = [min_of(r["t"], exp.t0) for r in m]
    host = [r.get("host", {}) for r in m]
    fig, ax = plt.subplots(2, 1, figsize=(8, 5), sharex=True)
    if any("containers" in h for h in host):  # the office PC: every container
        names = sorted({c["name"] for h in host for c in h.get("containers", []) if c.get("mine")})
        for n in names:
            ax[0].plot(xs, [next((c["cpu"] for c in h.get("containers", []) if c["name"] == n), None) for h in host], label=n.replace("oap-", ""), lw=1)
            ax[1].plot(xs, [next((c["mem_mb"] for c in h.get("containers", []) if c["name"] == n), None) for h in host], label=n.replace("oap-", ""), lw=1)
        ax[0].set_ylabel("container CPU %")
        ax[1].set_ylabel("container memory (MB)")
        free = ax[1].twinx()
        free.plot(xs, [h.get("free_mb") for h in host], color="#111827", ls="--", lw=1, label="free memory on the PC")
        free.set_ylabel("PC free MB")
        ax[0].legend(fontsize=6, ncol=4)
    else:  # this computer: the server process and the database
        ax[0].plot(xs, [r.get("server", {}).get("cpu") for r in m], label="exam server CPU % (100 = one core)", color="#1d4ed8")
        ax[0].plot(xs, [r.get("generator_cpu") for r in m], label="whole computer CPU %", color="#94a3b8")
        ax[0].set_ylabel("CPU %")
        ax[0].legend(fontsize=7)
        ax[1].plot(xs, [r.get("server", {}).get("rss_mb") for r in m], label="exam server memory", color="#1d4ed8")
        ax[1].plot(xs, [r.get("postgres", {}).get("rss_mb") for r in m], label="database memory", color="#16a34a")
        ax[1].plot(xs, [r.get("host", {}).get("free_mb") for r in m], label="free memory on the computer", color="#111827", ls="--")
        ax[1].set_ylabel("MB")
        ax[1].legend(fontsize=7)
    ax[1].set_xlabel("minutes since the start")
    for s in exp.steps:
        for a in ax:
            a.axvline(min_of(num(s["started"]), exp.t0), color="#cbd5e1", lw=0.8)
    for a in ax:
        a.grid(alpha=0.25)
    fig.suptitle("The machine that runs the server", fontsize=9)
    return fig_image(fig, out)


def endpoint_table(exp: Exp, limit=18):
    rows = sorted([r for r in exp.stats if r["Name"] != "Aggregated" and r["Type"] != "TIME"], key=lambda r: -(num(r["Request Count"]) or 0))[:limit]
    data = [["What", "Requests", "Failed", "Median ms", "95% ms", "99% ms", "Max ms", "per s"]]
    for r in rows:
        data.append([r["Name"], int(num(r["Request Count"]) or 0), int(num(r["Failure Count"]) or 0), round(num(r["50%"]) or 0), round(num(r["95%"]) or 0), round(num(r["99%"]) or 0),
                     round(num(r["Max Response Time"]) or 0), round(num(r["Requests/s"]) or 0, 2)])
    a = exp.agg()
    if a:
        data.append(["All requests", int(num(a["Request Count"]) or 0), int(num(a["Failure Count"]) or 0), round(num(a["50%"]) or 0), round(num(a["95%"]) or 0), round(num(a["99%"]) or 0),
                     round(num(a["Max Response Time"]) or 0), round(num(a["Requests/s"]) or 0, 2)])
    return table(data, [58 * mm, 18 * mm, 14 * mm, 20 * mm, 18 * mm, 18 * mm, 18 * mm, 14 * mm])


def time_metrics(exp: Exp):
    return [r for r in exp.stats if r["Type"] == "TIME"]


def verdict(exp: Exp):
    o = exp.outcome
    if not o:
        return "Not judged (no staged ramp)."
    users = o.get("last_healthy_users", 0)
    kind = o.get("result")
    if kind == "broke":
        return f"Broke at the step of {o.get('users')} candidates: {o.get('reason')}. The last step that stayed healthy was {users} candidates."
    if kind == "protected":
        return f"Stopped on purpose at the step of {o.get('users')} candidates to protect the computer: {o.get('reason')}. The last healthy step was {users} candidates."
    if kind == "cap":
        return f"Reached the highest step ({users} candidates) without breaking. The real limit is higher than the test went."
    return str(o)


def bottleneck_text(exp: Exp):
    o = exp.outcome or {}
    if o.get("result") not in ("broke", "protected") or not exp.metrics:
        return ""
    t_end = num(exp.steps[-1]["ended"]) if exp.steps else None
    window = [r for r in exp.metrics if t_end and t_end - 40 <= r["t"] <= t_end]   # the last 40 s of the step that broke
    cpu = [r.get("server", {}).get("cpu") for r in window if r.get("server", {}).get("cpu") is not None]
    ccpu = [c["cpu"] for r in window for c in r.get("host", {}).get("containers", []) if c.get("mine") and c["name"].endswith("api-1")]
    vals = sorted(cpu or ccpu or [0])
    top = vals[len(vals) // 2]
    free = min([r.get("host", {}).get("free_mb", 10 ** 9) for r in window] or [10 ** 9])
    log = jload(exp.dir / "server_log_summary.json", {})
    if o.get("result") == "protected":
        return "The computer ran short of memory first (it also runs other applications), so memory, not the exam server, was the limit."
    if log.get("pool_timeouts"):
        return (f"What broke first: the exam server ran out of database connections. Its log shows {log['pool_timeouts']} 'connection pool' time-outs (the pool allows 15 connections at once and "
                f"a request waits up to 30 s for one). At that moment the server's processor was only at about {round(top)}% and memory was fine: it was waiting, not working, and while it waited it "
                f"stopped answering even the health check.")
    if top >= 85:
        return f"Most likely limit: the exam server's processor. It was at about {round(top)}% (100% is one core) while response times grew."
    return (f"Most likely limit: waiting, not computing. Response times grew while the server's processor was only at about {round(top)}%, which points to the database "
            f"connection pool (15 connections) or the request thread pool (40 threads). Free memory stayed above {free if free < 10 ** 9 else 'n/a'} MB.")


def highlights(exps):
    """What stood out, in plain words, from the scenarios that were run."""
    out = []
    sec = lambda r, k="50%": round((num(r.get(k)) or 0) / 1000, 1)
    for e in sorted((x for x in exps if x.scenario == "login"), key=lambda x: num(x.meta.get("users")) or 0):
        a, lg = e.agg(), e.endpoint("auth login")
        fail = 100.0 * (num(a.get("Failure Count")) or 0) / max(num(a.get("Request Count")) or 1, 1)
        out.append(f"Sign-in storm, {e.meta.get('users')} candidates within seconds: a sign-in took {sec(lg)} s (95%: {sec(lg, '95%')} s); {fail:.1f}% of all requests failed.")
    for e in (x for x in exps if x.scenario == "start"):
        st = e.endpoint("start exam")
        out.append(f"Start storm, {e.meta.get('users')} candidates pressing Start together: starting took {sec(st)} s in the middle and up to {sec(st, 'Max Response Time')} s; "
                   f"{num(st.get('Failure Count')) or 0:.0f} of {num(st.get('Request Count')) or 0:.0f} starts failed.")
    for e in (x for x in exps if x.scenario == "submit"):
        tm = e.endpoint("submit: time until marked")
        out.append(f"Submit storm, {e.meta.get('users')} candidates submitting together: submitting itself was quick, but it took {round(sec(tm))} s (middle) and "
                   f"{round(sec(tm, 'Max Response Time'))} s (last) until every attempt was marked: marking works through them two at a time.")
    for e in (x for x in exps if x.scenario == "code"):
        tm = e.endpoint("code run: time until the result")
        out.append(f"Coding burst, {e.meta.get('users')} programs run at once: the result came back after {sec(tm)} s in the middle and {sec(tm, 'Max Response Time')} s at worst.")
    for e in (x for x in exps if x.scenario == "big"):
        def g(n):
            ms = num(e.endpoint(n).get("50%")) or 0
            return f"{ms:.0f} ms" if ms < 1000 else f"{ms / 1000:.1f} s"
        out.append(f"Large data (a few examiners at once): the question bank and candidate lists answered in about {g('big: question bank page')} to {g('big: candidates page')}; an exam's "
                   f"results page {g('big: results page')}, its analytics {g('big: analytics')}, the CSV export {g('big: export csv')}.")
    for e in (x for x in exps if x.scenario == "soak" and x.history):
        mem = [r.get("server", {}).get("rss_mb") for r in e.metrics if r.get("server")]
        if mem:
            third = max(len(mem) // 3, 1)
            first, last = sum(mem[:third]) / third, sum(mem[-third:]) / third
            out.append(f"Soak, {e.meta.get('label')}: held for {round((e.meta.get('ended', 0) - e.meta.get('started', 0)) / 60)} minutes; server memory {round(first)} MB at the start, "
                       f"{round(last)} MB at the end ({'no growth' if last < 1.15 * first else 'it grew'}); {e.agg().get('Failure Count', 0)} failed requests.")
    return out


def advice(exps):
    """Ranked improvements, only where the numbers above point at them."""
    out = []
    pool = sum((jload(e.dir / "server_log_summary.json", {}) or {}).get("pool_timeouts", 0) for e in exps)
    if pool:
        out.append("Database connections (first and most important): raise the pool well above 15 (and the database's connection limit with it) and make a request give up after a few seconds "
                   "with a clear 'busy, try again' instead of waiting 30 s. Stop the picture and video upload handlers from doing database work while holding up the whole server.")
    if any(x.scenario == "start" for x in exps):
        out.append("Starting an exam builds the candidate's whole paper in one go: spread the start (stagger candidates by a minute) or make the start lighter before large intakes.")
    if any(x.scenario == "submit" for x in exps):
        out.append("Marking after a submit storm works two at a time: raise the number of marking workers if a large group finishes together.")
    if any(x.scenario == "big" for x in exps):
        out.append("Results, analytics and exports are worked out from scratch on every request: keep a stored summary per exam if exams with thousands of finished candidates are expected.")
    out.append("Re-run this test after any change, to prove the number went up.")
    return out


def chapter(name: str, run_id: str, work: Path):
    run_dir = RESULTS / run_id
    exps = [Exp(p) for p in sorted(run_dir.iterdir()) if p.is_dir() and (p / "meta.json").exists()]
    by = lambda *kinds: [e for e in exps if e.scenario in kinds]
    run = jload(run_dir / "run.json", {})
    story = [Paragraph(name, H1), Paragraph(f"Run <b>{run_id}</b> on <b>{run.get('host', '')}</b>, {run.get('candidates', '?')} test candidates, exam of "
                                            f"{sum(len(v) for v in run.get('questions', {}).values())} questions with every proctoring rule on (camera pictures every 15 s, screen pictures every 60 s).", P)]
    for e in by("ramp"):
        story += [Paragraph(f"Staged ramp: {e.meta.get('label')}", H2), Paragraph(verdict(e), P), Paragraph("Slowest 95% is the worst 95th-percentile time among saving an answer, the clock and the exam state during the step.", SM)]
        b = bottleneck_text(e)
        if b:
            story.append(Paragraph(b, P))
        if e.steps:
            data = [["Step", "Candidates", "Result", "Requests/s", "Failed %", "Slowest 95% ms", "Why"]]
            for s in e.steps:
                data.append([s["step"], s["users"], s["result"], s["rps"], s["fail_pct"], s["p95_ms"], s["reason"]])
            story.append(table(data, [12 * mm, 22 * mm, 18 * mm, 22 * mm, 18 * mm, 26 * mm, 62 * mm]))
        for fn, fig in (("ramp", ramp_figure), ("res", resource_figure)):
            img = fig(e, work / f"{run_id}-{e.meta.get('label')}-{fn}.png")
            if img:
                story += [Spacer(1, 4), img]
        story += [Paragraph("What each request cost over the whole ramp", H2), endpoint_table(e)]
    storms = by("login", "start", "submit", "code")
    if storms:
        story.append(Paragraph("Storms: everybody at the same moment", H2))
        data = [["Scenario", "People", "Requests", "Failed", "95% ms (all)", "Time-based results", "Meaning"]]
        meaning = {"login": "everybody signs in within about a minute", "start": "everybody presses Start together", "submit": "everybody submits together; then we wait until all are marked",
                   "code": "everybody runs a program together (2 run at a time)"}
        for e in storms:
            a = e.agg()
            tm = "; ".join(f"{r['Name']}: median {round((num(r['50%']) or 0) / 1000, 1)} s, 95% {round((num(r['95%']) or 0) / 1000, 1)} s, longest {round((num(r['Max Response Time']) or 0) / 1000, 1)} s" for r in time_metrics(e))
            data.append([e.meta.get("label"), e.meta.get("users"), int(num(a.get("Request Count")) or 0), int(num(a.get("Failure Count")) or 0), round(num(a.get("95%")) or 0), tm or "-", meaning.get(e.scenario, "")])
        story.append(table(data, [28 * mm, 14 * mm, 18 * mm, 14 * mm, 20 * mm, 52 * mm, 36 * mm]))
        for e in storms:
            story += [Paragraph(f"{e.meta.get('label')}: the slowest steps", SM), endpoint_table(e, 8)]
    for e in by("big"):
        story += [Paragraph(f"Large data: {e.meta.get('label')}", H2), Paragraph("An examiner reading a question bank of thousands, thousands of candidates, and an exam with finished attempts "
                                                                              "(see the setup note for the sizes). Times are per request.", P), endpoint_table(e, 14)]
    for e in by("soak"):
        story += [Paragraph(f"Soak: {e.meta.get('label')}", H2), Paragraph("A long run at a steady level: does it slow down or use more and more memory over time?", P)]
        for fn, fig in (("ramp", ramp_figure), ("res", resource_figure)):
            img = fig(e, work / f"{run_id}-{e.meta.get('label')}-{fn}.png")
            if img:
                story += [Spacer(1, 4), img]
        story.append(endpoint_table(e, 10))
    clean = jload(run_dir / "cleanup" / "compare.json")
    if clean:
        story.append(Paragraph("Cleanup proof", H2))
        story.append(Paragraph(("CLEAN: after the cleanup every table holds exactly what it held before the test." if clean["ok"] else "NOT CLEAN: see the table.") +
                               f" Database {clean['database_mb'][0]} MB before, {clean['database_mb'][1]} MB after; storage {clean['storage_mb'][0]} MB / {clean['storage_files'][0]} files before, "
                               f"{clean['storage_mb'][1]} MB / {clean['storage_files'][1]} files after. Counted {clean['before_at']} and {clean['after_at']}.", P))
        diff = [["Table", "Before", "After", "Status"]] + [[r["table"], r["before"], r["after"], r["status"]] for r in clean["tables"] if r["status"] != "same"]
        if len(diff) > 1:
            story.append(table(diff, [60 * mm, 25 * mm, 25 * mm, 30 * mm]))
            story.append(Paragraph("'expected' rows are the Super Admin's own sign-in notes made while the test data was set up; they are real activity and are kept.", SM))
    shots = sorted((run_dir / "screens").glob("*.png")) if (run_dir / "screens").exists() else []
    if shots:
        story.append(PageBreak())
        story.append(Paragraph("Screenshots", H2))
        from PIL import Image as PI
        for s in shots:
            w, h = PI.open(s).size
            width = 160 * mm
            story.append(KeepTogether([Paragraph(s.stem.replace("-", " ").replace("_", " "), SM), Image(str(s), width=width, height=min(width * h / w, 200 * mm)), Spacer(1, 6)]))
    return story, exps


def summary(chapters):
    out = [Paragraph("Summary", H1)]
    for name, exps in chapters:
        ramps = [e for e in exps if e.scenario == "ramp" and e.outcome]
        if not ramps:
            continue
        best = max(ramps, key=lambda e: e.outcome.get("last_healthy_users", 0))
        o = best.outcome
        healthy = o.get("last_healthy_users", 0)
        steps = [num(s["rps"]) or 0 for s in best.steps]
        out.append(Paragraph(f"<b>{name}</b>", P))
        out.append(Paragraph(f"It carried <b>{healthy} candidates</b> taking a fully proctored exam at the same time with no failures and response times under 2 seconds. "
                             f"{verdict(best)} The most requests it served was about {round(max(steps or [0]))} per second. "
                             f"<b>Recommended working limit: about {int(healthy * 0.7 // 5 * 5) or healthy} candidates at one time</b> (70% of the healthy level, so there is room for a bad moment).", P))
        b = bottleneck_text(best)
        if b:
            out.append(Paragraph(b, P))
        for line in highlights(exps):
            out.append(Paragraph("&bull; " + line, P))
        out.append(Paragraph("What to improve, in order", H2))
        for line in advice(exps):
            out.append(Paragraph("&bull; " + line, P))
        out.append(Spacer(1, 4))
    out.append(Paragraph("How to read this report: a 'candidate' here is a script that does exactly what a real candidate's screen does (sign in, start, save answers, camera and "
                         "screen pictures, the clock, proctor events, code runs). The server load is real. The candidate's own laptop (camera, face detection) is not part of these numbers. "
                         "The system 'broke' when, for two checks of 30 seconds in a row, more than 1% of requests failed, or saving an answer, the clock or the exam state took longer than 2 seconds "
                         "for 95% of requests, or a container restarted or was killed, or the health check failed.", SM))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--env", action="append", required=True)
    p.add_argument("--run", action="append", required=True)
    p.add_argument("--out", default=str(HERE / "reports" / "load-test-report.pdf"))
    p.add_argument("--title", default="Load test report")
    a = p.parse_args()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    work = out.parent / "_charts"
    work.mkdir(exist_ok=True)
    story, chapters, bodies = [], [], []
    for name, run_id in zip(a.env, a.run):
        body, exps = chapter(name, run_id, work)
        bodies.append(body)
        chapters.append((name, exps))
    story += [Paragraph(a.title, ParagraphStyle("t", parent=H1, fontSize=24, spaceAfter=2)), Paragraph("KAUTILYA by GLOBX: how many candidates can one exam take, and where does it break?", P),
              Paragraph(time.strftime("%d %B %Y"), SM), Spacer(1, 10)] + summary(chapters)
    for body in bodies:
        story += [PageBreak()] + body
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm, title=a.title, author="Load test")
    doc.build(story)
    print(f"report written: {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
