"""The report card: the data, the PDF (read back as text), who may have it, the mail with the PDF (a stand-in SMTP server), the ZIP.
Shares its fixture and helpers with test_results."""
import io
import json
import smtplib
import zipfile
from email import message_from_bytes, policy
from types import SimpleNamespace

import pypdfium2 as pdfium
import pytest
from sqlalchemy import select
from test_exam_rules import PW, _login, _start, client  # noqa: F401  (client is a fixture)
from test_results import _answer, _exam, _results, _submit_and_wait, _wait

from app.db import SessionLocal
from app.models import MailOutbox, Test
from app.api import results as results_api
from app.services import mail
from app.services.report_card import card_pdf, is_real_email, question_status

API = "/api/v1"
REAL_DELIVER = mail.deliver_pending


def _text(pdf: bytes) -> str:
    doc = pdfium.PdfDocument(pdf)
    return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def _person(client, staff, tid, line):
    p = client.post(f"{API}/tests/{tid}/participants", headers=staff, json={"names": [line]}).json()["participants"][0]
    return _login(client, p["username"], p["password"]), p["assignment_id"]


@pytest.fixture(scope="module")
def exam(client):
    """A calculated exam: Right One (passed, has an e-mail), Wrong One (answered, not passed, has an e-mail), Empty One (did not attempt, login only), Absent One (never came)."""
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    evaluator = _login(client, "evaluator@globx.co.in", PW["evaluator@globx.co.in"])
    tid, q = _exam(client, creator, "Report Card Exam", cutoff=1)
    out = {"tid": tid, "creator": creator, "recruiter": recruiter, "evaluator": evaluator, "people": {}}
    for line, pick in (("Right One, right.one@example.com", ["a"]), ("Wrong One, wrong.one@example.com", ["b"]), ("Empty One", None), ("Absent One", "absent")):
        cand, asg = _person(client, recruiter, tid, line)
        name = line.split(",")[0]
        at = None
        if pick != "absent":
            at = _start(client, cand, asg)
            if pick:
                _answer(client, cand, at, q["mcq"], {"selected": pick})
            _submit_and_wait(client, cand, at)
        out["people"][name] = {"cand": cand, "asg": asg, "at": at}
    assert client.post(f"{API}/tests/{tid}/calculate", headers=evaluator).status_code == 200
    _wait(lambda: _results(client, creator, tid)["calculated_at"], "the calculation")
    return out


def _declare(client, exam, on=True):
    r = client.post(f"{API}/tests/{exam['tid']}/declare", headers=exam["evaluator"], json={"declared": on})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_numbers_and_the_text_of_the_pdf_and_no_answer_key_in_either(client, exam):
    right = exam["people"]["Right One"]["at"]
    d = client.get(f"{API}/attempts/{right}/report-card", headers=exam["creator"]).json()            # staff may preview before the results are declared
    assert d["candidate"]["name"] == "Right One" and d["candidate"]["email"] == "right.one@example.com" and d["declared"] is False
    assert d["exam"]["title"] == "Report Card Exam" and d["exam"]["department"] == "Technical" and d["exam"]["minutes_allowed"] == 30 and d["exam"]["pass_mark"] == 1
    assert d["score"]["score"] == 1 and d["score"]["max"] == 18 and d["score"]["percent"] == 5.6 and d["score"]["result"] == "passed" and d["score"]["result_label"] == "Passed"
    assert d["rank"] == 1 and d["of"] == 3 and d["highest"] == 5.6 and d["class_average"] == 1.9
    assert d["attempted"] == 1 and d["questions"] == 4 and d["report_no"].startswith("RC-")
    assert [(s["title"], s["score"], s["max"]) for s in d["sections"]] == [("All", 1, 18)]
    assert [(q["title"], q["status"], q["kind"]) for q in d["sections"][0]["questions"]] == [
        ("Report Card Exam mcq", "Correct", "Choice"), ("Report Card Exam short", "Not answered", "Written"), ("Report Card Exam long", "Not answered", "Written"), ("Report Card Exam code", "Not answered", "Coding")]
    assert {k["kind"]: (k["score"], k["max"]) for k in d["kinds"]} == {"Choice": (1, 1), "Written": (0, 7), "Coding": (0, 10)}
    wrong = client.get(f"{API}/attempts/{exam['people']['Wrong One']['at']}/report-card", headers=exam["creator"]).json()
    assert wrong["score"]["result"] == "not_passed" and wrong["sections"][0]["questions"][0]["status"] == "Incorrect"
    empty = client.get(f"{API}/attempts/{exam['people']['Empty One']['at']}/report-card", headers=exam["creator"]).json()
    assert empty["score"]["result"] == "not_attempted" and empty["candidate"]["email"] == ""      # a made-up login address is never shown as an e-mail

    r = client.get(f"{API}/attempts/{right}/report-card.pdf", headers=exam["creator"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert 'filename="report-card-Right-One-Report-Card-Exam.pdf"' in r.headers["content-disposition"]
    text = _text(r.content)
    for word in ("ASSESSMENT REPORT CARD", "Right One", "Report Card Exam", "PASSED", "5.6%", "1 of 3", "Performance by section", "Question-wise result", "Correct", "Not answered", "PREVIEW"):
        assert word in text, word
    # the answer key never reaches the card: not the model answers, not the reference program, not the options
    for secret in ("alpha is first", "a full explanation", "print(2*n)", "Clarity"):
        assert secret not in text and secret not in json.dumps(d), secret
    assert "options" not in json.dumps(d) and "model_answer" not in json.dumps(d)


def test_who_may_have_a_report_card_and_when(client, exam):
    right, wrong = exam["people"]["Right One"], exam["people"]["Wrong One"]
    asha = right["cand"]
    for path in ("report-card", "report-card.pdf"):
        r = client.get(f"{API}/attempts/{right['at']}/{path}", headers=asha)
        assert r.status_code == 409 and "not been declared" in r.text                                  # the candidate waits for the declaration
    assert client.get(f"{API}/attempts/{right['at']}/report-card", headers=exam["recruiter"]).status_code == 200   # staff who may view results
    assert client.get(f"{API}/attempts/{right['at']}/report-card").status_code == 401
    assert client.get(f"{API}/attempts/nope/report-card", headers=asha).status_code == 404
    _declare(client, exam)
    r = client.get(f"{API}/attempts/{right['at']}/report-card.pdf", headers=asha)
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and "PREVIEW" not in _text(r.content)   # declared: no preview tag
    assert client.get(f"{API}/attempts/{right['at']}/report-card", headers=asha).json()["declared"] is True
    assert client.get(f"{API}/attempts/{right['at']}/report-card", headers=wrong["cand"]).status_code == 404   # never another candidate's
    assert client.get(f"{API}/attempts/{right['at']}/report-card.pdf", headers=wrong["cand"]).status_code == 404
    me = next(a for a in client.get(f"{API}/me/assignments", headers=asha).json() if a["assignment_id"] == right["asg"])
    assert me["result"]["attempt_id"] == right["at"]
    with SessionLocal() as db:                                                                          # an exam that keeps its results from candidates
        t = db.get(Test, exam["tid"])
        t.settings = {**(t.settings or {}), "show_result_to_candidate": False}
        db.commit()
    assert client.get(f"{API}/attempts/{right['at']}/report-card.pdf", headers=asha).status_code == 409
    assert client.get(f"{API}/attempts/{right['at']}/report-card.pdf", headers=exam["recruiter"]).status_code == 200
    with SessionLocal() as db:
        t = db.get(Test, exam["tid"])
        t.settings = {**(t.settings or {}), "show_result_to_candidate": True}
        db.commit()
    _declare(client, exam, on=False)
    assert client.get(f"{API}/attempts/{right['at']}/report-card.pdf", headers=asha).status_code == 409     # withdrawn: gone again
    _declare(client, exam)


def test_the_zip_holds_every_finished_candidate(client, exam):
    r = client.get(f"{API}/tests/{exam['tid']}/report-cards.zip", headers=exam["recruiter"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert len(z.namelist()) == 3 and all(n.endswith(".pdf") and z.read(n).startswith(b"%PDF") for n in z.namelist())   # Absent One has no attempt, so no card
    assert any("Right-One" in n for n in z.namelist())
    assert client.get(f"{API}/tests/{exam['tid']}/report-cards.zip", headers=exam["people"]["Right One"]["cand"]).status_code == 403


def _outbox():
    with SessionLocal() as db:
        return [(m.to, m.status, m.attach, m.error) for m in db.scalars(select(MailOutbox).where(MailOutbox.kind == "report_card").order_by(MailOutbox.to))]


class FakeSmtp:
    """Stands in for the mail server: remembers what was sent, can refuse the login."""
    sent, connects, refuse_login = [], [], False

    def __init__(self, host, port, timeout=0):
        FakeSmtp.connects.append((host, port))

    def starttls(self):
        pass

    def login(self, user, password):
        if FakeSmtp.refuse_login:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    def send_message(self, msg):
        FakeSmtp.sent.append(message_from_bytes(msg.as_bytes(), policy=policy.default))

    def quit(self):
        pass

    def close(self):
        pass


@pytest.fixture()
def smtp(monkeypatch):
    FakeSmtp.sent, FakeSmtp.connects, FakeSmtp.refuse_login = [], [], False
    settings = lambda: SimpleNamespace(smtp_host="smtp.test", smtp_port=587, smtp_user="support@globx.co.in", smtp_password="x", smtp_from="KAUTILYA <support@globx.co.in>", smtp_tls=True)  # noqa: E731
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(mail, "get_settings", settings)
    monkeypatch.setattr(results_api, "get_settings", settings)
    monkeypatch.setattr(mail, "deliver_pending", lambda db: 0)   # the background sweeper must not send while a test is counting; the test calls the real one itself
    return FakeSmtp


def _deliver():
    with SessionLocal() as db:
        return REAL_DELIVER(db)


def test_declaring_queues_one_mail_per_real_address_and_the_mail_carries_the_pdf(client, exam, smtp):
    with SessionLocal() as db:                                                                          # (the background sweeper may already have logged them: send them now)
        for m in db.scalars(select(MailOutbox).where(MailOutbox.kind == "report_card")):
            m.status, m.error = "queued", ""
        db.commit()
    boxes = _outbox()
    assert [b[0] for b in boxes] == ["right.one@example.com", "wrong.one@example.com"]                  # not Empty One (made-up address), not Absent One
    assert {b[2] for b in boxes} == {exam["people"]["Right One"]["at"], exam["people"]["Wrong One"]["at"]}
    again = _declare(client, exam, on=False)
    assert again["mails"] == {}
    second = _declare(client, exam)
    assert second["mails"] == {"queued": 0, "requeued": 0, "already": 2, "no_email": 1}                 # declaring again sends nothing twice
    res = _results(client, exam["creator"], exam["tid"])
    assert res["mail"]["no_email"] == 1 and res["mail"]["smtp"] is True
    assert _row_mail(res, "Empty One") == "no_email" and _row_mail(res, "Absent One") is None

    _deliver()                                                                                          # (other tests' mails may be waiting too: only the report cards are counted)
    assert len(smtp.connects) == 1 and len([m for m in smtp.sent if m["Subject"].startswith("Your report card")]) == 2   # one connection for the whole batch
    msg = next(m for m in smtp.sent if m["To"] == "right.one@example.com" and m["Subject"].startswith("Your report card"))
    assert msg["From"] == "KAUTILYA <support@globx.co.in>" and msg["Subject"] == "Your report card - Report Card Exam"
    body = msg.get_body(("plain",)).get_content()
    assert "Dear Right One," in body and "Result: Passed" in body and "Score: 1 / 18 (5.6%)" in body and "KAUTILYA by GLOBX" in body
    att = next(p for p in msg.iter_attachments())
    assert att.get_content_type() == "application/pdf" and att.get_filename() == "report-card-Right-One-Report-Card-Exam.pdf"
    pdf = att.get_payload(decode=True)
    assert pdf.startswith(b"%PDF") and "Right One" in _text(pdf) and "PREVIEW" not in _text(pdf)
    res = _results(client, exam["creator"], exam["tid"])
    assert res["mail"]["sent"] == 2 and _row_mail(res, "Right One") == "sent"


def _row_mail(res, name):
    return next(r for r in res["rows"] if r["name"] == name).get("mail")


def test_a_refused_login_fails_the_batch_once_with_its_reason_and_send_again_tries_again(client, exam, smtp):
    with SessionLocal() as db:
        for m in db.scalars(select(MailOutbox).where(MailOutbox.kind == "report_card")):
            db.delete(m)
        db.commit()
    assert client.post(f"{API}/tests/{exam['tid']}/email-report-cards", headers=exam["evaluator"]).json() == {"queued": 2, "requeued": 0, "already": 0, "no_email": 1}
    smtp.refuse_login = True
    _deliver()
    assert len(smtp.connects) == 1 and smtp.sent == []                                                  # one try, not one per mail and not again in ten seconds
    boxes = _outbox()
    assert [b[1] for b in boxes] == ["failed", "failed"] and all("Username and Password not accepted" in b[3] for b in boxes)
    res = _results(client, exam["creator"], exam["tid"])
    assert res["mail"]["failed"] == 2 and "Username and Password not accepted" in res["mail"]["error"]
    _deliver()
    assert len(smtp.connects) == 1                                                                      # failed mails are not retried by themselves

    smtp.refuse_login = False
    assert client.post(f"{API}/tests/{exam['tid']}/email-report-cards", headers=exam["evaluator"]).json() == {"queued": 0, "requeued": 2, "already": 0, "no_email": 1}
    _deliver()
    assert [b[1] for b in _outbox()] == ["sent", "sent"] and len(smtp.sent) == 2
    assert client.post(f"{API}/tests/{exam['tid']}/email-report-cards", headers=exam["evaluator"]).json()["already"] == 2
    assert client.post(f"{API}/tests/{exam['tid']}/email-report-cards", headers=exam["recruiter"]).status_code == 403
    assert client.post(f"{API}/tests/{exam['tid']}/email-report-cards", headers=exam["creator"]).status_code == 403


def test_a_mail_whose_result_was_withdrawn_before_it_was_sent_is_not_sent(client, exam, smtp):
    with SessionLocal() as db:
        for m in db.scalars(select(MailOutbox).where(MailOutbox.kind == "report_card")):
            db.delete(m)
        db.commit()
    assert _declare(client, exam, on=False)["declared"] is False
    assert client.post(f"{API}/tests/{exam['tid']}/email-report-cards", headers=exam["evaluator"]).status_code == 409   # declare first
    _declare(client, exam)                                                                              # queues two
    _declare(client, exam, on=False)                                                                    # ...withdrawn before the sweeper sent them
    _deliver()
    assert smtp.sent == [] and [b[1] for b in _outbox()] == ["failed", "failed"] and "not been declared" in _outbox()[0][3]
    _declare(client, exam)


def test_a_refused_address_fails_that_mail_only(client, exam, smtp, monkeypatch):
    with SessionLocal() as db:
        for m in db.scalars(select(MailOutbox).where(MailOutbox.kind == "report_card")):
            db.delete(m)
        db.commit()
    client.post(f"{API}/tests/{exam['tid']}/email-report-cards", headers=exam["evaluator"])
    real = FakeSmtp.send_message

    def pick(self, msg):
        if msg["To"].startswith("right"):
            raise smtplib.SMTPRecipientsRefused({msg["To"]: (550, b"no such mailbox")})
        return real(self, msg)
    monkeypatch.setattr(FakeSmtp, "send_message", pick)
    _deliver()
    states = {b[0]: b[1] for b in _outbox()}
    assert states == {"right.one@example.com": "failed", "wrong.one@example.com": "sent"}


def test_a_long_card_with_an_odd_name_still_makes_a_pdf():
    qs = [{"n": i, "title": f"Question {i} <b>&</b> " + "very long " * 30, "kind": "Choice", "marks": 1, "score": 1 if i % 3 else 0, "status": "Correct" if i % 3 else "Incorrect"} for i in range(1, 201)]
    d = {"report_no": "RC-TEST", "generated_at": "now", "declared": True, "declared_at": "then", "candidate": {"name": "Zoë <Ünïcode> 李雷 & Sons " * 3, "login": "zoe", "email": ""},
         "exam": {"title": "A very long exam title " * 8, "department": "HR", "taken_at": "x", "submitted_at": "y", "minutes_allowed": 60, "minutes_taken": None, "pass_mark": 0},
         "score": {"score": 0, "max": 0, "percent": 0, "result": "no_pass_mark", "result_label": ""}, "rank": None, "of": 0, "class_average": 0, "highest": 0, "attempted": 0, "questions": 200,
         "note": "", "sections": [{"title": "S", "score": 133, "max": 200, "percent": 66.5, "average": 100, "questions": qs}, {"title": "Empty", "score": 0, "max": 0, "percent": 0, "average": 0, "questions": []}],
         "kinds": [], "highlights": []}
    pdf = card_pdf(d)
    doc = pdfium.PdfDocument(pdf)
    assert pdf.startswith(b"%PDF") and len(doc) >= 5
    text = _text(pdf)
    assert "Zo" in text and "Page 1 of" in text and "Question 200" in text and "PASSED" not in text and "NOT PASSED" not in text


def test_small_rules():
    assert is_real_email("a@b.com") and not is_real_email("raj@exam.local") and not is_real_email("RAJ@EXAM.LOCAL") and not is_real_email("") and not is_real_email("nope")
    assert question_status({"answered": False, "score": 0, "marks": 1}) == "Not answered"
    assert question_status({"answered": True, "score": 1, "marks": 1}) == "Correct" and question_status({"answered": True, "score": 0.5, "marks": 1}) == "Partly correct"
    assert question_status({"answered": True, "score": 0, "marks": 1}) == "Incorrect" and question_status({"answered": True, "score": -0.25, "marks": 1}) == "Incorrect"
    assert question_status({"answered": True, "score": 0, "marks": 1, "status": "review"}) == "Awaiting marking"
