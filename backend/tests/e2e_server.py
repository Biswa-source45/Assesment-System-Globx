"""Server for the Playwright suite (frontend/e2e): seeds a throw-away copy of the database (<name>_test)
and serves the API on port 8001. The generated demo passwords are written to the JSON file given as argument."""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_settings  # noqa: E402

# the browser tests write camera pictures too: into a throw-away folder, never into the real user-assets
e2e_storage = Path(tempfile.gettempdir()) / "oap-e2e-storage"
shutil.rmtree(e2e_storage, ignore_errors=True)
os.environ["STORAGE_DIR"] = str(e2e_storage)

if not os.environ.get("RUN_AI"):  # the browser tests must not spend money or depend on the network; RUN_AI=1 keeps the real provider
    os.environ["LLM_PROVIDER"] = "none"

# Mail: never the real server (the repo .env may hold it). A stand-in "mail server" writes every mail as a file in <storage>/mail, so a test can read it.
os.environ.update(SMTP_HOST="smtp.test", SMTP_PORT="587", SMTP_USER="", SMTP_PASSWORD="", SMTP_FROM="KAUTILYA <support@globx.co.in>", SMTP_TLS="false")
mail_dir = e2e_storage / "mail"
mail_dir.mkdir(parents=True)
import smtplib  # noqa: E402


class _FakeSmtp:
    def __init__(self, host, port, timeout=0):
        pass

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        (mail_dir / f"{__import__('time').time_ns()}.eml").write_bytes(msg.as_bytes())

    def quit(self):
        pass

    def close(self):
        pass


smtplib.SMTP = _FakeSmtp

base, _, name = get_settings().database_url.rpartition("/")
os.environ["DATABASE_URL"] = f"{base}/{name}" if name.endswith("_test") else f"{base}/{name}_test"
get_settings.cache_clear()

from app.seed import seed  # noqa: E402

res = seed(reset=True)
creds = {e: p for e, p, _ in res["staff"]}
creds["candidate"] = res["candidate_password"]
Path(sys.argv[1]).write_text(json.dumps(creds), encoding="utf-8")

import atexit  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

import httpx  # noqa: E402
import uvicorn  # noqa: E402

# candidate code runs through the judge service, exactly as in production (here a plain process on a local port; the container is checked by hostile.py)
judge = subprocess.Popen([sys.executable, "-m", "uvicorn", "judge_service:app", "--port", "8002", "--log-level", "warning"], cwd=Path(__file__).resolve().parents[1])
atexit.register(judge.kill)
for _ in range(100):
    try:
        httpx.get("http://127.0.0.1:8002/health").raise_for_status()
        break
    except httpx.HTTPError:
        time.sleep(0.1)
else:
    sys.exit("the judge service did not start")
os.environ["JUDGE_URL"] = "http://127.0.0.1:8002"
get_settings.cache_clear()

if not os.environ.get("RUN_AI"):
    # The browser tests must not call OpenAI. This stands in for the AI step of the paper upload: it answers with a fixed question file built
    # from the picture ids it was given (a graph question, a question whose options are pictures with an answer "chosen by the AI", one broken
    # question, a written question, and a note). A paper whose text holds SLOW takes 8 seconds, so a test can press Cancel.
    import json as _json

    from app.api import exam_pack

    import copy as _copy
    import re as _re

    def _question_ai(msg, pictures):
        """The question editor's "write or change a question with AI": the words in the request decide what the stand-in does."""
        fences = _re.findall(r"<<<PAPER\n(.*?)\nPAPER>>>", msg, _re.S)
        request = fences[-1]
        if "SLOW" in request:
            time.sleep(8)
        pack = lambda q, done=("Wrote the question.",): {"request_ok": True, "changes": list(done), "notes": [], "question": q}  # noqa: E731
        if "REFUSE" in request:
            return {"request_ok": False, "notes": ["That is not a question."]}
        if "THE QUESTION AS IT IS NOW" in msg:
            q, done = _json.loads(fences[0]), []
            q.pop("_note", None)
            if "fifth" in request:
                q["options"] = [*q["options"], "Sapporo"]
                done.append("Added a fifth option, Sapporo.")
            if "harder" in request:
                q["statement"] += " Think carefully."
                done.append("Made the question harder.")
            if "marks" in request:
                q["marks"] = 3
                done.append("Marks are now 3.")
            return pack(q, done or ["Nothing needed to change."])
        mcq = {"type": "mcq_single", "title": "Capital of Japan", "statement": "What is the capital of Japan?", "options": ["Osaka", "Tokyo", "Kyoto", "Nagoya"], "correct": ["b"], "marks": 1, "difficulty": "easy"}
        if "BROKEN" in request:
            return pack({**mcq, "correct": ["z"]})
        if "CODING" in request:
            c = _copy.deepcopy(exam_pack.EXAMPLES["coding"])
            c.pop("starter")
            return pack(c)
        if "SQL" in request:
            return pack(_copy.deepcopy(exam_pack.EXAMPLES["sql"]))
        if "WRITTEN" in request:
            return pack(_copy.deepcopy(exam_pack.EXAMPLES["short"]))
        if "Check-me" in request:  # the independent answer below says b: the key says a
            return pack({**mcq, "statement": "Check-me: what is the capital of Japan?", "correct": ["a"]})
        if pictures:
            return pack({**mcq, "title": "City from the picture", "statement": "Which city is shown? [[IMAGE 1]]"})
        return pack(mcq)

    def _fake_ai(system, msg, pictures):
        if system.startswith("You write ONE question"):
            return _json.dumps(_question_ai(msg, pictures)), "stop"
        if system.startswith("You answer a multiple choice"):
            return _json.dumps({"answer": ["b"]}), "stop"
        if system.startswith("You write a correct Python 3"):
            return _json.dumps({"source": exam_pack.EXAMPLES["coding"]["reference"]["source"]}), "stop"
        if system.startswith("You write one correct SQLite"):
            return _json.dumps({"sql": exam_pack.EXAMPLES["sql"]["reference_sql"]}), "stop"
        if "SLOW" in msg:
            time.sleep(8)
        ids = [p[0] for p in pictures if p[0].startswith("IMAGE")]
        pic = lambda n: ids[n] if len(ids) > n else (ids[-1] if ids else "IMAGE 1")  # noqa: E731
        return _json.dumps({"sections": [
            {"title": "Reasoning", "questions": [
                {"type": "mcq_single", "title": "Speed from a graph", "statement": "What is the speed at 2 seconds?", "images": [pic(0)] if ids else [],
                 "options": ["10 km/h", "20 km/h", "30 km/h", "40 km/h"], "correct": ["b"], "marks": 2},
                {"type": "mcq_single", "title": "Next figure", "statement": "Which figure completes the series?", "marks": 2, "answer_from_ai": True,
                 "options": [{"text": "A", "image": pic(1)}, {"text": "B", "image": pic(2)}, {"text": "C", "image": pic(3)}, {"text": "D", "image": pic(4)}], "correct": ["c"]},
                {"type": "mcq_single", "title": "Broken question", "statement": "The AI gave a wrong answer letter.", "options": ["x", "y"], "correct": ["z"]}]},
            {"title": "Written", "questions": [
                {"type": "short", "title": "Capital of France", "statement": "Name the capital city of France.", "model_answer": "Paris", "marks": 3}]}],
            "notes": ["The paper mentions a chart on page 3 that could not be read."]}), "stop"

    exam_pack.ask_ai_for_pack = _fake_ai

    # the small focused calls (hidden SQL data, a generator program for a described test case, the test-case table) get fixed answers too
    from app.services import ai as _ai
    _ai.ai_generate_sql_datasets = lambda *a, **k: [{"data": "INSERT INTO employees VALUES (1,'Zed',50000),(2,'Amy',50001);", "purpose": "a salary of exactly 50000"}]
    _ai.ai_generator_program = lambda *a, **k: "print('(' * 3000 + ')' * 3000)"
    _ai.ai_extract_test_cases = lambda *a, **k: []
    _ai.ai_generate_inputs = lambda *a, **k: []

uvicorn.run("app.main:app", port=8001, log_level="warning")
