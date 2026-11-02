import json
import time

from fastapi.testclient import TestClient


def _wait(c, url, h, done=("done", "error"), key="status", tries=120):
    for _ in range(tries):
        r = c.get(url, headers=h).json()
        if r.get(key) in done:
            return r
        time.sleep(0.5)
    raise AssertionError(f"timeout waiting for {url}")


def test_full_candidate_flow():
    from app.seed import seed
    pw = {e: p for e, p, _ in seed(reset=True)["staff"]}
    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/v1/auth/login", json={"email": "recruiter@globx.co.in", "password": pw["recruiter@globx.co.in"]})
        assert r.status_code == 200
        staff = {"Authorization": "Bearer " + r.json()["access_token"]}
        assert c.post("/api/v1/auth/login", json={"email": "recruiter@globx.co.in", "password": "nope"}).status_code == 401
        otp = c.post("/api/v1/auth/otp/request", json={"email": "sneha.patnaik@example.com"}).json()["demo_otp"]
        assert c.post("/api/v1/auth/otp/verify", json={"email": "sneha.patnaik@example.com", "otp": "000000" if otp != "000000" else "111111"}).status_code == 400
        tok = c.post("/api/v1/auth/otp/verify", json={"email": "sneha.patnaik@example.com", "otp": otp}).json()["access_token"]
        h = {"Authorization": "Bearer " + tok}
        asg = [a for a in c.get("/api/v1/me/assignments", headers=h).json() if a["test"]["title"] == "Practice Test"][0]
        at = c.post(f"/api/v1/assignments/{asg['assignment_id']}/start", headers=h, json={"consent": {}, "system_check": {}}).json()["attempt_id"]
        st = c.get(f"/api/v1/attempts/{at}", headers=h).json()
        blob = json.dumps(st)
        assert '"correct"' not in blob and "reference" not in blob and "model_answer" not in blob
        for s in st["sections"]:
            for q in s["questions"]:
                if q["type"].startswith("mcq"):
                    opt = next(o["id"] for o in q["options"] if o["text"] == "O(log n)")
                    assert c.put(f"/api/v1/attempts/{at}/answers/{q['id']}", headers=h, json={"response": {"selected": [opt]}, "seq": 1}).status_code == 200
                elif q["type"] == "coding":
                    sid = c.post(f"/api/v1/attempts/{at}/code/{q['id']}/submit", headers=h,
                                 json={"language": "python", "source": "a,b=map(int,input().split())\nprint(a+b)"}).json()["submission_id"]
                    res = _wait(c, f"/api/v1/submissions/{sid}", h)
                    assert res["score"] == 10 and "cases" not in res["result"]
        assert c.post(f"/api/v1/attempts/{at}/submit", headers=h, json={}).status_code == 200
        for _ in range(120):
            s = c.get(f"/api/v1/attempts/{at}", headers=h).json()["attempt"]["status"]
            if s in ("review_pending", "evaluated"):
                break
            time.sleep(0.5)
        assert s in ("review_pending", "evaluated")
        rep = c.get(f"/api/v1/reports/attempts/{at}", headers=staff).json()
        assert rep["attempt"]["total_score"] >= 11  # 1 (MCQ) + 10 (coding) + short answer
        # candidate cannot open staff report
        assert c.get(f"/api/v1/reports/attempts/{at}", headers=h).status_code == 403
