"""Makes the test data of one load-test run through the application's own API (no custom code runs inside the server).
Everything made carries the run id (for example LT-20261120-2100) in its name, so it can be found and erased again (cleanup.sql).

  LT_HOST=http://localhost:8001 LT_ADMIN_EMAIL=... LT_ADMIN_PASSWORD=... python setup_data.py create --candidates 200

The admin password is read from the environment and is never written anywhere. The temporary staff user and the candidates get random passwords
that are saved in results/<run id>/ (git-ignored, only on this computer)."""
import argparse
import csv
import json
import os
import sys
import time

from common import Api, host, new_run_id, random_password, run_dir

TYPES = ["mcq_single", "mcq_multi", "short", "long", "coding", "sql"]


def mcq(title, dept, i):
    right = "abcd"[i % 4]
    return {"department_id": dept, "type": "mcq_single", "title": title, "body": f"<p>{title}: choose the right option.</p>", "marks": 2,
            "difficulty": ["easy", "medium", "hard"][i % 3], "skills": ["load", "mcq"],
            "config": {"options": [{"id": k, "text": f"Option {k.upper()} of {title}", "correct": k == right} for k in "abcd"]}}


def short(title, dept):
    return {"department_id": dept, "type": "short", "title": title, "body": f"<p>{title}: explain in two sentences.</p>", "marks": 5,
            "difficulty": "medium", "skills": ["load", "written"],
            "config": {"model_answer": "A queue keeps first in first out order.", "keywords": ["queue", "first", "order"], "max_words": 120}}


def coding(title, dept):
    return {"department_id": dept, "type": "coding", "title": title, "body": "<p>Read n and print 2*n.</p>", "marks": 10, "difficulty": "easy",
            "skills": ["load", "coding"],
            "config": {"languages": ["python"], "reference": {"language": "python", "source": "n=int(input())\nprint(2*n)"}},
            "cases": [{"visibility": "open", "input": "2\n", "expected": "4"}, {"visibility": "open", "input": "5\n", "expected": "10"},
                      {"visibility": "hidden", "input": "7\n", "expected": "14"}, {"visibility": "hidden", "input": "11\n", "expected": "22"}]}


def create(a) -> None:
    run = a.run_id or new_run_id()
    out = run_dir(run)
    api = Api(verify=not a.insecure).login(os.environ["LT_ADMIN_EMAIL"], os.environ["LT_ADMIN_PASSWORD"])
    t0 = time.time()
    print(f"run {run} on {host()}")

    dept = api.post("/departments", {"name": f"{run} Department", "question_types": TYPES})["id"]
    ids = {"mcq": [], "short": [], "coding": []}
    for i in range(a.mcq):
        ids["mcq"].append(api.post("/questions", mcq(f"{run} MCQ {i + 1:03d}", dept, i))["id"])
    for i in range(a.short):
        ids["short"].append(api.post("/questions", short(f"{run} Written {i + 1:02d}", dept))["id"])
    for i in range(a.coding):
        q = api.post("/questions", coding(f"{run} Coding {i + 1:02d}", dept))
        if not q["config"].get("validated"):
            raise SystemExit("The coding question was not validated: is the code judge running?")
        ids["coding"].append(q["id"])
    print(f"questions: {sum(len(v) for v in ids.values())} ({time.time() - t0:.0f} s)")

    proctoring = {"enabled": True, "webcam": True, "fullscreen": True, "block_paste": True, "block_multi_display": True, "screen_share": True,
                  "live_view": True, "evidence": "pictures", "snapshot_seconds": 15, "screenshot_seconds": 60, "tab_switch_limit": 3,
                  "face_limit": 5, "face_min_seconds": 3, "face_zone": 70}
    test = api.post("/tests", {"department_id": dept, "title": f"{run} Exam", "duration_min": 90, "cutoff": 20, "shuffle_questions": True,
                               "shuffle_options": True, "description": "Load test. Safe to delete.",
                               "settings": {"proctoring": proctoring, "min_question_seconds": 5, "show_result_to_candidate": True}})
    tid = test["id"]
    sections = {}
    for title, key in (("Multiple choice", "mcq"), ("Written", "short"), ("Coding", "coding")):
        if not ids[key]:
            continue
        sid = api.post(f"/tests/{tid}/sections", {"title": title})["sections"][-1]["id"]
        sections[key] = sid
        for qid in ids[key]:
            api.post(f"/sections/{sid}/items", {"kind": "question", "question_id": qid})
    api.post(f"/tests/{tid}/publish")
    print(f"exam {tid} published ({time.time() - t0:.0f} s)")

    staff_email, staff_pw = f"lt-admin-{run.lower()}@loadtest.invalid", random_password()
    api.post("/users", {"email": staff_email, "name": f"{run} Staff", "roles": ["org_admin"], "password": staff_pw})

    rows = []
    for start in range(0, a.candidates, 200):
        names = [f"lt{i + 1:05d} {run} Candidate" for i in range(start, min(a.candidates, start + 200))]
        rows += api.post(f"/tests/{tid}/participants", {"names": names}, timeout=600)["participants"]
        print(f"candidates: {len(rows)} / {a.candidates} ({time.time() - t0:.0f} s)", flush=True)
    with open(out / "candidates.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["username", "password", "assignment_id"])
        for r in rows:
            w.writerow([r["username"], r["password"], r["assignment_id"]])

    browser_exam = None
    if a.browser_exam:
        bt = api.post("/tests", {"department_id": dept, "title": f"{run} Browser Exam", "duration_min": 90, "cutoff": 2, "shuffle_questions": False, "shuffle_options": False,
                                 "description": "Load test with real browsers. Safe to delete.",
                                 "settings": {"proctoring": {"enabled": True, "webcam": False, "fullscreen": False, "block_paste": True, "block_multi_display": False,
                                                              "screen_share": False, "live_view": False, "evidence": "pictures", "tab_switch_limit": 50, "face_limit": 0},
                                              "min_question_seconds": 0}})
        bsid = api.post(f"/tests/{bt['id']}/sections", {"title": "Quick check"})["sections"][-1]["id"]
        for qid in ids["mcq"][:6]:
            api.post(f"/sections/{bsid}/items", {"kind": "question", "question_id": qid})
        api.post(f"/tests/{bt['id']}/publish")
        names = [f"{run} Browser Candidate {i + 1:02d}" for i in range(a.browser_exam)]
        brows = api.post(f"/tests/{bt['id']}/participants", {"names": names})["participants"]
        browser_exam = {"exam_id": bt["id"], "title": f"{run} Browser Exam", "candidates": [{"username": r["username"], "password": r["password"]} for r in brows]}
        print(f"browser exam {bt['id']} with {len(brows)} candidates")
    run_info = {"run_id": run, "host": host(), "department_id": dept, "exam_id": tid, "sections": sections, "questions": ids,
                "staff_email": staff_email, "staff_password": staff_pw, "candidates": len(rows), "browser_exam": browser_exam, "made_in_s": round(time.time() - t0, 1),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    (out / "run.json").write_text(json.dumps(run_info, indent=2), encoding="utf-8")
    print(f"done in {time.time() - t0:.0f} s. Saved in {out}")


def add_candidates(a) -> None:
    """More logins for the same exam (a bigger test needs more people)."""
    from common import load_run
    run = load_run(a.run_id)
    out = run_dir(run["run_id"])
    api = Api(verify=not a.insecure).login(os.environ["LT_ADMIN_EMAIL"], os.environ["LT_ADMIN_PASSWORD"])
    have = run["candidates"]
    rows = []
    for start in range(have, have + a.candidates, 200):
        names = [f"lt{i + 1:05d} {run['run_id']} Candidate" for i in range(start, min(have + a.candidates, start + 200))]
        rows += api.post(f"/tests/{run['exam_id']}/participants", {"names": names}, timeout=600)["participants"]
        print(f"added {len(rows)} / {a.candidates}", flush=True)
    with open(out / "candidates.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow([r["username"], r["password"], r["assignment_id"]])
    run["candidates"] = have + len(rows)
    (out / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create")
    c.add_argument("--run-id", default="")
    c.add_argument("--candidates", type=int, default=200)
    c.add_argument("--mcq", type=int, default=30)
    c.add_argument("--short", type=int, default=5)
    c.add_argument("--coding", type=int, default=3)
    c.add_argument("--browser-exam", type=int, default=0, help="also make a small exam for this many real-browser candidates")
    c.add_argument("--insecure", action="store_true", help="do not check the HTTPS certificate (a local test copy)")
    m = sub.add_parser("more")
    m.add_argument("--run-id", default="")
    m.add_argument("--candidates", type=int, required=True)
    m.add_argument("--insecure", action="store_true")
    args = p.parse_args()
    if not os.environ.get("LT_ADMIN_EMAIL") or not os.environ.get("LT_ADMIN_PASSWORD"):
        sys.exit("Set LT_ADMIN_EMAIL and LT_ADMIN_PASSWORD in the environment (they are never saved).")
    create(args) if args.cmd == "create" else add_candidates(args)
