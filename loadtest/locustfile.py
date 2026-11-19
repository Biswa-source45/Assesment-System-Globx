"""Virtual candidates and staff for the load tests. Each one sends exactly what the real screens send, at the real rhythm:
sign in, start, read the exam, then every 15 s the clock, every ~15 s a camera picture, every 60 s a screen picture, an answer saved a few seconds after
each question is opened, now and then a proctor event and a code run. Face detection and the camera run in the candidate's browser, so a script only sends
what the browser would send.

Pick what to run by naming classes:  locust -f locustfile.py Steady Staff     (see run_load.py, which starts everything)
  Steady       one candidate taking the exam for as long as the test runs (S1, S8)
  LoginStorm   signs in and leaves (S2)
  StartStorm   signs in, waits for a set moment, then everybody starts the exam together (S3)
  SubmitStorm  takes the exam, then everybody submits at a set moment; measures how long until every attempt is marked (S4)
  CodeBurst    everybody runs a program at a set moment (S5)
  Staff        an examiner with the live monitor open, sometimes results and analytics (S6)
  BigReader    an examiner reading the big lists and the big exam (S7)
Settings come from environment variables (LT_*), see run_load.py."""
import csv
import itertools
import os
import random
import re
import time

import gevent
from locust import HttpUser, constant, events, task
from locust.exception import StopUser

from common import RESULTS, load_run, picture_pool

RUN = load_run()
CANDIDATES = list(csv.DictReader(open(RESULTS / RUN["run_id"] / "candidates.csv", encoding="utf-8")))
CAM, SCREEN = picture_pool()
HOST = os.environ.get("LT_HOST", RUN["host"])
INSECURE = os.environ.get("LT_INSECURE") == "1"
WORKERS = int(os.environ.get("LT_WORKERS", "1"))
STATIC = os.environ.get("LT_STATIC", "1") == "1"
SUBMIT_ON_STOP = os.environ.get("LT_SUBMIT_ON_STOP", "0") == "1"
OFFSET = int(os.environ.get("LT_OFFSET", "0"))  # candidates already used by an earlier scenario are skipped
BARRIER = float(os.environ.get("LT_BARRIER", "0"))  # wall-clock moment (epoch seconds) for the storm scenarios
_counter = itertools.count()
_assets = None

SHORT_TEXT = ("A queue keeps the first item that came in as the first item to go out, so the order of arrival is the order of service. "
              "A stack does the opposite and serves the newest item first. ") * 2
CODE = "n = int(input())\nprint(2 * n)\n"


def iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def next_candidate(env):
    worker = getattr(env.runner, "worker_index", None) or 0
    i = OFFSET + worker + WORKERS * next(_counter)
    if i >= len(CANDIDATES):
        print(f"No more candidate logins ({len(CANDIDATES)}): make more with setup_data.py more", flush=True)
        raise StopUser()
    return CANDIDATES[i]


class Base(HttpUser):
    abstract = True
    host = HOST
    wait_time = constant(1)

    def on_start(self):
        if INSECURE:
            self.client.verify = False
        self.refresh_at = 0

    # one request, counted under a steady name; a 401 means the 15-minute token ran out: refresh once and try again
    def call(self, method, path, name, **kw):
        kw.setdefault("timeout", 60)
        with self.client.request(method, path, name=name, catch_response=True, **kw) as r:
            if r.status_code == 401 and self.tokens and name != "auth refresh":
                r.success()
                if self.refresh():
                    return self.call(method, path, name, **kw)
                r.failure("401 after refresh")
            elif r.status_code >= 400:
                r.failure(f"{r.status_code} {r.text[:80]}")
            return r

    tokens = None

    def sign_in(self, user, password):
        r = self.call("POST", "/api/v1/auth/login", "auth login", json={"email": user, "password": password})
        if r.status_code != 200:
            raise StopUser()
        self.tokens = r.json()
        self.client.headers["Authorization"] = "Bearer " + self.tokens["access_token"]
        self.refresh_at = time.time() + 13 * 60
        return self.tokens

    def refresh(self):
        r = self.client.post("/api/v1/auth/refresh", json={"refresh_token": self.tokens["refresh_token"]}, name="auth refresh")
        if r.status_code != 200:
            return False
        self.tokens = {**self.tokens, **r.json()}
        self.client.headers["Authorization"] = "Bearer " + self.tokens["access_token"]
        self.refresh_at = time.time() + 13 * 60
        return True

    def open_site(self):
        """The first visit of a browser: the page and its files (a real browser then keeps them)."""
        global _assets
        r = self.client.get("/", name="static page")
        if _assets is None:
            _assets = sorted(set(re.findall(r'(?:src|href)="(/assets/[^"]+\.(?:js|css))"', r.text)))
        for a in _assets:
            self.client.get(a, name="static file")


class Candidate(Base):
    abstract = True

    def sign_in_as_candidate(self):
        self.cred = next_candidate(self.environment)
        if STATIC:
            self.open_site()
        self.sign_in(self.cred["username"], self.cred["password"])
        self.call("GET", "/api/v1/auth/me", "auth me")
        self.call("GET", "/api/v1/me/assignments", "my exams")

    def start_exam(self):
        r = self.call("POST", f"/api/v1/assignments/{self.cred['assignment_id']}/start", "start exam",
                      json={"consent": {"accepted": True, "text_version": "2026-11"},
                            "system_check": {"camera": True, "displays": 1, "vm_suspected": False, "renderer": "load", "browser": "locust"}})
        if r.status_code != 200:
            raise StopUser()
        self.at = r.json()["attempt_id"]
        st = self.call("GET", f"/api/v1/attempts/{self.at}", "exam state").json()
        self.questions = [q for s in st["sections"] for q in s["questions"]]
        self.section_of = {q["id"]: s["id"] for s in st["sections"] for q in s["questions"]}
        self.sections = [s["id"] for s in st["sections"]]
        self.seq = {}
        self.entered = set()
        self.cur = -1
        return st

    def enter_section(self, sid):
        if sid not in self.entered:
            self.entered.add(sid)
            self.call("POST", f"/api/v1/attempts/{self.at}/sections/{sid}/enter", "section enter")

    def open_question(self, i):
        self.cur = i % len(self.questions)
        q = self.questions[self.cur]
        self.enter_section(self.section_of[q["id"]])
        self.call("POST", f"/api/v1/attempts/{self.at}/questions/{q['id']}/seen", "question seen")
        return q

    def answer(self, q):
        if q["type"] == "coding":
            return
        self.seq[q["id"]] = self.seq.get(q["id"], 0) + 1
        if q["type"].startswith("mcq"):
            pick = random.choice(q["options"])["id"]
            resp = {"selected": [pick]}
        else:
            resp = {"text": SHORT_TEXT[: random.randint(120, 400)], "html": "<p>" + SHORT_TEXT[: random.randint(120, 400)] + "</p>"}
        self.call("PUT", f"/api/v1/attempts/{self.at}/answers/{q['id']}", "save answer", json={"response": resp, "flagged": random.random() < 0.05, "seq": self.seq[q["id"]]})

    def clock(self):
        self.call("GET", f"/api/v1/attempts/{self.at}/clock", "clock")

    def camera_picture(self):
        self.call("POST", f"/api/v1/attempts/{self.at}/proctor/snapshot", "camera picture", data={"kind": "webcam", "faces": "1"},
                  files={"image": ("webcam.jpg", random.choice(CAM), "image/jpeg")})

    def screen_picture(self):
        self.call("POST", f"/api/v1/attempts/{self.at}/proctor/snapshot", "screen picture", data={"kind": "screen"},
                  files={"image": ("screen.jpg", random.choice(SCREEN), "image/jpeg")})

    def proctor_event(self):
        self.call("POST", f"/api/v1/attempts/{self.at}/proctor/events", "proctor event",
                  json={"events": [{"type": random.choice(["paste", "copy"]), "duration_ms": 0, "payload": {}, "started_at": iso()}]})

    def run_code(self, q, kind="run"):
        r = self.call("POST", f"/api/v1/attempts/{self.at}/code/{q['id']}/{kind}", f"code {kind}",
                      json={"language": "python", "source": CODE, "custom_input": "21\n" if kind == "run" else None})
        if r.status_code != 200:
            return None
        sid, t0 = r.json()["submission_id"], time.time()
        for _ in range(90):  # the screen asks again every second
            gevent.sleep(1)
            s = self.call("GET", f"/api/v1/submissions/{sid}", "code result")
            if s.status_code == 200 and s.json()["status"] not in ("queued", "running", "pending"):
                break
        events.request.fire(request_type="TIME", name=f"code {kind}: time until the result", response_time=(time.time() - t0) * 1000, response_length=0, exception=None, context={})
        return sid

    def submit(self, name="submit exam"):
        self.call("POST", f"/api/v1/attempts/{self.at}/submit", name, json={})

    def wait_for(self, moment):
        while moment and time.time() < moment:
            gevent.sleep(min(0.5, max(0, moment - time.time())))


class Steady(Candidate):
    """S1 / S8: one candidate in the exam for as long as the test runs."""

    @task
    def take_the_exam(self):
        self.sign_in_as_candidate()
        self.start_exam()
        now = time.time()
        due = {"clock": now + random.uniform(2, 15), "camera": now + random.uniform(2, 15), "screen": now + random.uniform(5, 60),
               "nav": now, "event": now + random.uniform(60, 240)}
        answer_at, typing_until, code_at = None, 0, None
        try:
            while True:
                now = time.time()
                if now >= self.refresh_at:
                    self.refresh()
                if now >= due["clock"]:
                    self.clock()
                    due["clock"] = now + 15
                if now >= due["camera"]:
                    self.camera_picture()
                    due["camera"] = now + 15
                if now >= due["screen"]:
                    self.screen_picture()
                    due["screen"] = now + 60
                if now >= due["event"]:
                    self.proctor_event()
                    due["event"] = now + random.uniform(120, 300)
                if now >= due["nav"]:  # the candidate opens the next question
                    q = self.open_question(self.cur + 1)
                    due["nav"] = now + random.uniform(30, 70)
                    answer_at = now + random.uniform(3, 25)
                    typing_until = answer_at + (60 if q["type"] in ("short", "long") else 0)
                    code_at = now + random.uniform(20, 90) if q["type"] == "coding" else None
                if answer_at and now >= answer_at:  # the page saves a changed answer within 10 s
                    self.answer(self.questions[self.cur])
                    answer_at = now + 10 if now < typing_until else None
                if code_at and now >= code_at:
                    q = self.questions[self.cur]
                    self.run_code(q)
                    if random.random() < 0.3:
                        self.run_code(q, "submit")
                    code_at = None
                gevent.sleep(0.25)
        finally:
            if SUBMIT_ON_STOP:
                self.submit("submit exam (at the end)")


class LoginStorm(Candidate):
    """S2: the sign-in and the first screen, then gone."""

    @task
    def sign_in_once(self):
        self.sign_in_as_candidate()
        raise StopUser()


class StartStorm(Candidate):
    """S3: everybody signs in, waits for LT_BARRIER, then starts the exam together."""

    @task
    def start_together(self):
        self.sign_in_as_candidate()
        self.wait_for(BARRIER)
        self.start_exam()
        raise StopUser()


class SubmitStorm(Candidate):
    """S4: everybody takes the exam, then submits together at LT_BARRIER; then we wait until the attempt is marked."""

    @task
    def submit_together(self):
        self.sign_in_as_candidate()
        self.start_exam()
        self.open_question(0)
        while BARRIER and time.time() < BARRIER:
            self.clock()
            self.camera_picture()
            gevent.sleep(random.uniform(10, 20))
        for q in self.questions[:5]:
            self.answer(q)
        t0 = time.time()
        self.submit()
        for _ in range(900):
            gevent.sleep(1)
            r = self.call("GET", f"/api/v1/attempts/{self.at}", "exam state (waiting to be marked)")
            if r.status_code == 200 and r.json()["attempt"]["status"] in ("review_pending", "evaluated"):
                break
        events.request.fire(request_type="TIME", name="submit: time until marked", response_time=(time.time() - t0) * 1000, response_length=0, exception=None, context={})
        raise StopUser()


class CodeBurst(Candidate):
    """S5: everybody runs a program at LT_BARRIER."""

    @task
    def run_together(self):
        self.sign_in_as_candidate()
        self.start_exam()
        coding = [q for q in self.questions if q["type"] == "coding"]
        if not coding:
            raise StopUser()
        self.open_question(self.questions.index(coding[0]))
        self.wait_for(BARRIER)
        self.run_code(coding[0])
        raise StopUser()


class Staff(HttpUser):
    """S6: an examiner. The live monitor refreshes every 5 s; results and analytics are opened now and then."""
    host = HOST
    wait_time = constant(1)
    fixed_count = int(os.environ.get("LT_STAFF", "0"))

    def on_start(self):
        if INSECURE:
            self.client.verify = False
        r = self.client.post("/api/v1/auth/login", json={"email": RUN["staff_email"], "password": RUN["staff_password"]}, name="staff login")
        if r.status_code != 200:
            raise StopUser()
        self.client.headers["Authorization"] = "Bearer " + r.json()["access_token"]
        self.tid = RUN["exam_id"]
        self.until = time.time() + 13 * 60

    def get(self, path, name):
        if time.time() > self.until:
            r = self.client.post("/api/v1/auth/login", json={"email": RUN["staff_email"], "password": RUN["staff_password"]}, name="staff login")
            if r.status_code == 200:
                self.client.headers["Authorization"] = "Bearer " + r.json()["access_token"]
                self.until = time.time() + 13 * 60
        self.client.get(path, name=name, timeout=120)

    @task(10)
    def monitor(self):
        self.get(f"/api/v1/tests/{self.tid}/monitor", "staff: live monitor")
        gevent.sleep(5)

    @task(2)
    def results(self):
        self.get(f"/api/v1/tests/{self.tid}/results?limit=50", "staff: results (50 rows)")

    @task(1)
    def analytics(self):
        self.get(f"/api/v1/tests/{self.tid}/analytics", "staff: analytics")

    @task(2)
    def lists(self):
        self.get("/api/v1/questions?limit=50&q=" + RUN["run_id"], "staff: question bank (50)")
        self.get("/api/v1/users?role=candidate&limit=50", "staff: candidates (50)")


class BigReader(Staff):
    """S7: an examiner reading the big lists and the big exam (needs run.json to know big_exam_id)."""
    fixed_count = 0

    @task(5)
    def bank(self):
        self.get(f"/api/v1/questions?limit=50&offset={random.randrange(0, 4000, 50)}", "big: question bank page")
        self.get("/api/v1/questions?limit=50&q=" + random.choice(["MCQ", "Written", "Coding", "01", "99"]), "big: question bank search")

    @task(5)
    def users(self):
        self.get(f"/api/v1/users?role=candidate&limit=50&offset={random.randrange(0, 4000, 50)}", "big: candidates page")
        self.get("/api/v1/users?role=candidate&limit=50&q=" + random.choice(["Candidate 0001", "Big", "00099"]), "big: candidates search")

    @task(4)
    def big_results(self):
        big = RUN.get("big_exam_id", self.tid)
        self.get(f"/api/v1/tests/{big}/results?limit=50&offset={random.randrange(0, 900, 50)}", "big: results page")
        self.get(f"/api/v1/tests/{big}/results?limit=0", "big: results summary")

    @task(1)
    def big_analytics(self):
        self.get(f"/api/v1/tests/{RUN.get('big_exam_id', self.tid)}/analytics", "big: analytics")

    @task(1)
    def big_export(self):
        self.get(f"/api/v1/tests/{RUN.get('big_exam_id', self.tid)}/export?format=csv", "big: export csv")


# the staged ramp (S1, S8) and its break rules live in shape.py; it is only loaded when asked for
if os.environ.get("LT_SHAPE") == "stages":
    from shape import StagesShape  # noqa: F401
