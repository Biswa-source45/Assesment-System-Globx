"""Participants with an email, the student sheet, editing a participant, and mailing the logins once the exam is published:
what the mail says, what the screen knows about every person's mail, and that nothing is changed when it cannot be sent."""
import io
import smtplib
from datetime import datetime, timezone
from email import message_from_bytes, policy
from types import SimpleNamespace

import openpyxl
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_exam_pack import _creator, _exam as _draft_exam
from test_exam_rules import PW, _login, _start, client  # noqa: F401  (client is a fixture)
from test_results import _exam as _published_exam

from app.api import tests as tests_api
from app.db import SessionLocal
from app.models import MailOutbox, Test, User
from app.services import invites as inv
from app.services import login_mail, mail

API = "/api/v1"
REAL_DELIVER = mail.deliver_pending


# ---------------------------------------------------------------- helpers
class FakeSmtp:
    """Stands in for the mail server: remembers what was sent, and refuses the addresses it is told to."""
    sent, refuse = [], set()

    def __init__(self, host, port, timeout=0):
        pass

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        if msg["To"] in FakeSmtp.refuse:
            raise smtplib.SMTPRecipientsRefused({msg["To"]: (550, b"no such mailbox")})
        FakeSmtp.sent.append(message_from_bytes(msg.as_bytes(), policy=policy.default))

    def quit(self):
        pass

    def close(self):
        pass


@pytest.fixture()
def smtp(monkeypatch):
    FakeSmtp.sent, FakeSmtp.refuse = [], set()
    cfg = lambda: SimpleNamespace(smtp_host="smtp.test", smtp_port=587, smtp_user="", smtp_password="", smtp_from="KAUTILYA <support@globx.co.in>",  # noqa: E731
                                  smtp_tls=False, public_base_url="https://exam.test")
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    for module in (mail, tests_api, login_mail):
        monkeypatch.setattr(module, "get_settings", cfg)
    monkeypatch.setattr(mail, "deliver_pending", lambda db: 0)   # the background sweeper must not send while a test is counting; the test sends itself
    return FakeSmtp


def _deliver():
    with SessionLocal() as db:
        return REAL_DELIVER(db)


def _recruiter(client):
    return _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])


def _add(client, h, tid, *lines, required=True):
    return client.post(f"{API}/tests/{tid}/participants", headers=h, json={"names": list(lines), "email_required": required})


def _people(client, h, tid, *lines, required=True):
    r = _add(client, h, tid, *lines, required=required)
    assert r.status_code == 200, r.text
    return {p["name"]: p for p in r.json()["participants"]}


def _table(client, h, tid):
    return client.get(f"{API}/tests/{tid}/candidates", headers=h).json()


def _row(table, name):
    return next(r for r in table["rows"] if r["name"] == name)


def _sign_in(client, who, password):
    return client.post(f"{API}/auth/login", json={"email": who, "password": password}).status_code


def _login_mails(email=None):
    with SessionLocal() as db:
        q = select(MailOutbox).where(MailOutbox.kind == "exam_login")
        if email:
            q = q.where(MailOutbox.to == email)
        return list(db.scalars(q.order_by(MailOutbox.created_at)))


# ---------------------------------------------------------------- the student sheet
def test_a_sheet_is_read_by_its_headings_and_every_unusable_row_is_named():
    csv_text = ("Full name,Email\nAsha Rao,asha@x.test\nVikram Das,VIKRAM@X.TEST\nSample Student,sample@example.com\n\n,nobody@x.test\nNo Email,\n"
                "Bad Mail,not-an-email\nAsha Again,asha@x.test\n")
    out = inv.parse_sheet(csv_text.encode(), "list.csv")
    assert out["lines"] == ["Asha Rao, asha@x.test", "Vikram Das, vikram@x.test"] and out["samples"] == 1   # the sample row is skipped, the email lower-cased
    assert out["problems"] == ["Row 6: the full name is missing", "Row 7: the email of No Email is missing", "Row 8: 'not-an-email' is not a valid email",
                               "Row 9: asha@x.test is in the sheet twice"]                                  # row numbers are the sheet's own, blank lines included


def test_the_columns_may_be_in_any_order_have_other_headings_or_none():
    assert inv.parse_sheet("Roll;Name;E-mail\n1;Ria Sen;ria@x.test\n".encode("utf-8-sig"), "a.csv")["lines"] == ["Ria Sen, ria@x.test"]     # other columns, ; and a BOM
    assert inv.parse_sheet(b"E-mail,Full name\nria@x.test,Ria Sen\n", "a.csv")["lines"] == ["Ria Sen, ria@x.test"]                           # the other way round
    assert inv.parse_sheet(b"asha@x.test,Asha Rao\nvik@x.test,Vik Das\n", "a.csv")["lines"] == ["Asha Rao, asha@x.test", "Vik Das, vik@x.test"]  # no headings, email first
    assert inv.parse_sheet(b"Asha Rao,asha@x.test\n", "a.csv")["lines"] == ["Asha Rao, asha@x.test"]                                       # no headings, name first
    assert inv.parse_sheet(b'"Rao, Asha",asha@x.test\n', "a.csv")["lines"] == ["Rao Asha, asha@x.test"]                                    # a comma in a name cannot split the line
    assert inv.parse_sheet("Name,Email\nJos\xe9 Silva,jose@x.test\n".encode("cp1252"), "a.csv")["lines"] == ["Jos\xe9 Silva, jose@x.test"]  # an older Excel's CSV


def test_an_excel_sheet_is_read_and_other_files_are_refused_plainly():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Full name", "Email", "Phone"])
    ws.append(["Asha Rao", "asha@x.test", 9876543210])
    ws.append(["Vikram Das", "vik@x.test", None])
    buf = io.BytesIO()
    wb.save(buf)
    assert inv.parse_sheet(buf.getvalue(), "list.xlsx")["lines"] == ["Asha Rao, asha@x.test", "Vikram Das, vik@x.test"]
    for name, data in (("old.xls", b"x"), ("list.pdf", b"x"), ("empty.csv", b"\n\n"), ("broken.xlsx", b"not a workbook")):
        with pytest.raises(HTTPException) as e:
            inv.parse_sheet(data, name)
        assert e.value.status_code == 422, name
    big = "Name,Email\n" + "".join(f"P {i},p{i}@x.test\n" for i in range(201))
    with pytest.raises(HTTPException) as e:
        inv.parse_sheet(big.encode(), "big.csv")
    assert "200" in e.value.detail


def test_the_sheet_endpoint_only_reads_and_only_for_those_who_manage_participants(client):
    h = _creator(client)
    tid = _draft_exam(client, h, title="Sheet exam")["id"]
    with SessionLocal() as db:
        before = db.scalar(select(func.count(User.id)))
    r = client.post(f"{API}/tests/{tid}/participants/sheet", headers=h, files={"file": ("list.csv", b"Full name,Email\nSheet One,sheet.one@x.test\n", "text/csv")})
    assert r.status_code == 200 and r.json()["lines"] == ["Sheet One, sheet.one@x.test"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(User.id))) == before                                      # nothing was created
    evaluator = _login(client, "evaluator@globx.co.in", PW["evaluator@globx.co.in"])
    assert client.post(f"{API}/tests/{tid}/participants/sheet", headers=evaluator, files={"file": ("l.csv", b"a,b", "text/csv")}).status_code == 403
    assert client.post(f"{API}/tests/{tid}/participants/sheet", headers=h, files={"file": ("l.csv", b"x" * 2_000_100, "text/csv")}).status_code == 422


# ---------------------------------------------------------------- adding people
def test_an_email_can_be_required_and_a_known_person_joins_the_next_exam_with_the_same_username(client):
    h = _creator(client)
    t1, t2, t3 = (_draft_exam(client, h, title=f"Join exam {i}")["id"] for i in (1, 2, 3))
    refused = _add(client, h, t1, "No Mail Person")
    assert refused.status_code == 422 and "add the email" in refused.json()["detail"]
    assert _add(client, h, t1, "No Mail Person", required=False).status_code == 200                  # scripts may still send a name alone

    first = _people(client, h, t1, "Asha Joiner, asha.joiner@mail.test")["Asha Joiner"]
    second = _people(client, h, t2, "Asha J, ASHA.JOINER@mail.test")["Asha Joiner"]                   # the same person: the same login, the account's own name
    assert second["existing"] is True and second["username"] == first["username"] and second["password"] != first["password"]
    assert _sign_in(client, first["username"], second["password"]) == 200 and _sign_in(client, first["username"], first["password"]) == 401

    again = _add(client, h, t2, "Asha Joiner, asha.joiner@mail.test")
    assert again.status_code == 422 and "already in this exam" in again.json()["detail"]
    staff = _add(client, h, t3, "Some Staff, creator@globx.co.in")
    assert staff.status_code == 422 and "staff" in staff.json()["detail"]
    twice = _add(client, h, t3, "Twice One, twice@mail.test", "Twice Two, twice@mail.test")
    assert twice.status_code == 422 and "twice" in twice.json()["detail"]


def test_a_person_taking_an_exam_cannot_be_added_to_another_one_meanwhile(client):
    creator, recruiter = _creator(client), _recruiter(client)
    live, _ = _published_exam(client, creator, "Busy exam")
    other = _draft_exam(client, creator, title="Other exam")["id"]
    p = _people(client, recruiter, live, "Bala Busy, bala.busy@mail.test")["Bala Busy"]
    _start(client, _login(client, p["username"], p["password"]), p["assignment_id"])
    r = _add(client, recruiter, other, "Bala Busy, bala.busy@mail.test")
    assert r.status_code == 422 and "taking another exam" in r.json()["detail"]


# ---------------------------------------------------------------- sending the logins
def test_nothing_changes_when_the_mail_server_is_not_set_up_or_the_exam_is_a_draft(client):
    creator, recruiter = _creator(client), _recruiter(client)
    tid, _ = _published_exam(client, creator, "No server exam")
    p = _people(client, recruiter, tid, "Nina Nomail, nina.nomail@mail.test")["Nina Nomail"]
    r = client.post(f"{API}/tests/{tid}/send-logins", headers=recruiter, json={})
    assert r.status_code == 422 and "not set up" in r.json()["detail"]
    assert _sign_in(client, p["username"], p["password"]) == 200                                       # her password is untouched
    assert client.post(f"{API}/assignments/{p['assignment_id']}/send-login", headers=recruiter).status_code == 422
    assert _login_mails("nina.nomail@mail.test") == []


def test_a_draft_exam_cannot_send_logins(client, smtp):
    creator, recruiter = _creator(client), _recruiter(client)
    tid = _draft_exam(client, creator, title="Draft send exam")["id"]
    p = _people(client, recruiter, tid, "Dora Draft, dora.draft@mail.test")["Dora Draft"]
    r = client.post(f"{API}/tests/{tid}/send-logins", headers=recruiter, json={})
    assert r.status_code == 422 and "Publish the exam first" in r.json()["detail"]
    assert _sign_in(client, p["username"], p["password"]) == 200 and _login_mails("dora.draft@mail.test") == []
    assert client.post(f"{API}/assignments/{p['assignment_id']}/send-login", headers=recruiter).status_code == 422


def test_logins_are_mailed_with_a_fresh_password_and_the_exam_details_and_the_record_shows_it(client, smtp):
    creator, recruiter = _creator(client), _recruiter(client)
    tid, _ = _published_exam(client, creator, "Mail exam")
    people = _people(client, recruiter, tid, "Asha Mailed, asha.mailed@mail.test", "Ben Mailed, ben.mailed@mail.test")
    people.update(_people(client, recruiter, tid, "Cara Nomail", required=False))
    old = {n: p["password"] for n, p in people.items()}

    out = client.post(f"{API}/tests/{tid}/send-logins", headers=recruiter, json={}).json()
    assert out["queued"] == 2 and out["no_email"] == 1 and out["busy"] == 0 and out["remaining"] == 0
    fresh = {p["name"]: p for p in out["participants"]}
    assert set(fresh) == {"Asha Mailed", "Ben Mailed"} and all(fresh[n]["password"] != old[n] for n in fresh)
    assert _sign_in(client, fresh["Asha Mailed"]["username"], old["Asha Mailed"]) == 401              # the earlier password stops working
    assert _sign_in(client, fresh["Asha Mailed"]["username"], fresh["Asha Mailed"]["password"]) == 200
    assert _sign_in(client, people["Cara Nomail"]["username"], old["Cara Nomail"]) == 200             # nobody was mailed: hers is untouched

    table = _table(client, recruiter, tid)
    assert _row(table, "Asha Mailed")["login_mail"]["state"] == "queued" and _row(table, "Cara Nomail")["login_mail"]["state"] == "no_email"
    assert table["logins"] == {"waiting": 0, "queued": 2, "sent": 0, "failed": 0, "changed": 0, "no_email": 1}

    _deliver()
    msgs = {m["To"]: m for m in smtp.sent if m["Subject"] == "Your login for Mail exam"}
    assert set(msgs) == {"asha.mailed@mail.test", "ben.mailed@mail.test"}
    msg = msgs["asha.mailed@mail.test"]
    text, page = msg.get_body(("plain",)).get_content(), msg.get_body(("html",)).get_content()
    assert "Dear Asha Mailed," in text and f"Username: {fresh['Asha Mailed']['username']}" in text and f"Password: {fresh['Asha Mailed']['password']}" in text
    assert f"https://exam.test/login?exam={tid}" in text and f"https://exam.test/login?exam={tid}" in page and "Open your exam" in page and "30 minutes" in text
    assert fresh["Asha Mailed"]["password"] in page and "KAUTILYA" in page
    row = _row(_table(client, recruiter, tid), "Asha Mailed")["login_mail"]
    assert row["state"] == "sent" and row["to"] == "asha.mailed@mail.test" and row["at"] and not row["error"]

    for m in _login_mails():                                                                            # the passwords are not kept in the outbox
        assert fresh["Asha Mailed"]["password"] not in (m.body or "") + (m.body_html or "") and m.status == "sent"

    again = client.post(f"{API}/tests/{tid}/send-logins", headers=recruiter, json={}).json()           # nobody is waiting: nothing is sent, no password changes
    assert again["queued"] == 0
    assert _sign_in(client, fresh["Asha Mailed"]["username"], fresh["Asha Mailed"]["password"]) == 200
    forced = client.post(f"{API}/tests/{tid}/send-logins", headers=recruiter, json={"again": True}).json()
    assert forced["queued"] == 2 and _sign_in(client, fresh["Asha Mailed"]["username"], fresh["Asha Mailed"]["password"]) == 401
    one = client.post(f"{API}/assignments/{people['Asha Mailed']['assignment_id']}/send-login", headers=recruiter)
    assert one.status_code == 200 and one.json()["participant"]["name"] == "Asha Mailed"
    assert client.post(f"{API}/assignments/{people['Cara Nomail']['assignment_id']}/send-login", headers=recruiter).status_code == 422   # no email: edit first


def test_a_person_taking_another_exam_is_not_given_a_new_password(client, smtp):
    creator, recruiter = _creator(client), _recruiter(client)
    live, _ = _published_exam(client, creator, "Live elsewhere exam")
    tid, _ = _published_exam(client, creator, "Mail busy exam")
    p = _people(client, recruiter, live, "Gus Busy, gus.busy@mail.test")["Gus Busy"]
    _start(client, _login(client, p["username"], p["password"]), p["assignment_id"])
    # the same account in a second exam (added before the first exam started in real life: here the account is attached directly)
    with SessionLocal() as db:
        from app.models import Assignment
        from app.core.security import new_token, sha256
        a1 = db.get(Assignment, p["assignment_id"])
        db.add(Assignment(test_id=tid, candidate_id=a1.candidate_id, token_hash=sha256(new_token(32))))
        db.commit()
    out = client.post(f"{API}/tests/{tid}/send-logins", headers=recruiter, json={}).json()
    assert out["queued"] == 0 and out["busy"] == 1
    assert _sign_in(client, p["username"], p["password"]) == 200


# ---------------------------------------------------------------- the wording
def _test(db, tid):
    return db.get(Test, tid)


def test_the_mail_wording_follows_the_exam_dates_in_india_time(client):
    creator = _creator(client)
    tid, _ = _published_exam(client, creator, "Wording exam")
    utc = timezone.utc
    with SessionLocal() as db:
        t = _test(db, tid)
        t.starts_at, t.ends_at = datetime(2026, 11, 21, 4, 30, tzinfo=utc), datetime(2026, 11, 21, 8, 30, tzinfo=utc)
        subject, text, page = login_mail.exam_login_mail(t, "Asha", "asha", "ash@globx123")
        assert subject == "Your login for Wording exam"
        assert "from 21 Nov 2026, 10:00 IST to 21 Nov 2026, 14:00 IST" in text and "from 21 Nov 2026, 10:00 IST to 21 Nov 2026, 14:00 IST" in page
        assert "Time allowed: 30 minutes" in text and "Once you press Start you have 30 minutes" in text and "finish before the exam closes" in text
        t.starts_at = None
        assert "at any time until 21 Nov 2026, 14:00 IST" in login_mail.exam_login_mail(t, "Asha", "asha", "p")[1]
        t.starts_at, t.ends_at = datetime(2026, 11, 21, 4, 30, tzinfo=utc), None
        text = login_mail.exam_login_mail(t, "Asha", "asha", "p")[1]
        assert "opens on 21 Nov 2026, 10:00 IST" in text and "finish before the exam closes" not in text
        t.starts_at = None
        text = login_mail.exam_login_mail(t, "Asha", "asha", "p")[1]
        assert "no fixed date" in text and "time that suits you" in text and "IST" not in text
        t.starts_at = t.ends_at = None
        # a name with markup cannot inject anything into the formatted mail
        page = login_mail.exam_login_mail(t, "<b>x</b> & Co", "u", "p")[2]
        assert "&lt;b&gt;x&lt;/b&gt; &amp; Co" in page and "<b>x</b> & Co" not in page
        db.rollback()


# ---------------------------------------------------------------- editing a participant, and the mail record
def test_an_edit_changes_the_details_but_mails_nothing_and_the_screen_says_the_new_address_was_not_mailed(client, smtp):
    creator, recruiter = _creator(client), _recruiter(client)
    tid, _ = _published_exam(client, creator, "Edit exam")
    people = _people(client, recruiter, tid, "Dev Edit, dev.old@mail.test", "Eve Other, eve.other@mail.test")
    dev = people["Dev Edit"]
    client.post(f"{API}/tests/{tid}/send-logins", headers=recruiter, json={})
    _deliver()
    before = len(_login_mails())

    bad = lambda **b: client.put(f"{API}/assignments/{dev['assignment_id']}/participant", headers=recruiter, json=b)  # noqa: E731
    assert bad(name="Dev", email="not-an-email").status_code == 422
    assert bad(name="  ", email="dev.new@mail.test").status_code == 422
    dup = bad(name="Dev", email="EVE.OTHER@mail.test")
    assert dup.status_code == 422 and "already used" in dup.json()["detail"]

    ok = bad(name="  Dev   Edited ", email="Dev.New@Mail.test")
    assert ok.status_code == 200 and ok.json() == {"name": "Dev Edited", "email": "dev.new@mail.test"}
    assert len(_login_mails()) == before                                                                     # saving mailed nobody
    table = _table(client, recruiter, tid)
    row = _row(table, "Dev Edited")
    assert row["login_mail"]["state"] == "email_changed" and row["login_mail"]["to"] == "dev.old@mail.test" and row["username"] == dev["username"]
    assert table["logins"]["changed"] == 1 and table["logins"]["waiting"] == 1 and _row(table, "Eve Other")["login_mail"]["state"] == "sent"

    out = client.post(f"{API}/tests/{tid}/send-logins", headers=recruiter, json={}).json()              # now it is sent, to the new address only
    assert out["queued"] == 1 and out["participants"][0]["name"] == "Dev Edited"
    _deliver()
    assert [m["To"] for m in smtp.sent if "Edit exam" in m["Subject"]].count("dev.new@mail.test") == 1
    row = _row(_table(client, recruiter, tid), "Dev Edited")["login_mail"]
    assert row["state"] == "sent" and row["to"] == "dev.new@mail.test"

    hist = client.get(f"{API}/assignments/{dev['assignment_id']}/login-mails", headers=recruiter).json()
    assert hist["email"] == "dev.new@mail.test" and [(m["to"], m["status"]) for m in hist["mails"]] == [("dev.new@mail.test", "sent"), ("dev.old@mail.test", "sent")]
    assert all(m["queued_at"] and m["sent_at"] for m in hist["mails"])


def test_a_refused_address_is_shown_as_not_delivered_with_the_reason_and_can_be_fixed_and_sent(client, smtp):
    creator, recruiter = _creator(client), _recruiter(client)
    tid, _ = _published_exam(client, creator, "Refused exam")
    eli = _people(client, recruiter, tid, "Eli Refused, eli.refused@mail.test")["Eli Refused"]
    smtp.refuse = {"eli.refused@mail.test"}
    client.post(f"{API}/tests/{tid}/send-logins", headers=recruiter, json={})
    _deliver()
    table = _table(client, recruiter, tid)
    lm = _row(table, "Eli Refused")["login_mail"]
    assert lm["state"] == "failed" and "refused" in lm["error"] and lm["to"] == "eli.refused@mail.test"
    assert table["logins"]["failed"] == 1 and table["logins"]["waiting"] == 1                            # failed ones are waiting again
    assert not [m for m in smtp.sent if m["To"] == "eli.refused@mail.test"]

    r = client.put(f"{API}/assignments/{eli['assignment_id']}/participant", headers=recruiter, json={"name": "Eli Refused", "email": "eli.fixed@mail.test"})
    assert r.status_code == 200
    assert client.post(f"{API}/assignments/{eli['assignment_id']}/send-login", headers=recruiter).status_code == 200
    _deliver()
    lm = _row(_table(client, recruiter, tid), "Eli Refused")["login_mail"]
    assert lm["state"] == "sent" and lm["to"] == "eli.fixed@mail.test"
    hist = client.get(f"{API}/assignments/{eli['assignment_id']}/login-mails", headers=recruiter).json()["mails"]
    assert [(m["to"], m["status"]) for m in hist] == [("eli.fixed@mail.test", "sent"), ("eli.refused@mail.test", "failed")] and hist[1]["sent_at"] is None


def test_the_state_of_a_mail_that_was_only_logged_or_has_no_address():
    logged = MailOutbox(to="a@mail.test", subject="s", body="b", kind="exam_login", status="logged")
    assert login_mail.mail_state("a@mail.test", [logged])["state"] == "failed" and "not set up" in login_mail.mail_state("a@mail.test", [logged])["error"]
    assert login_mail.mail_state("raj@exam.local", [])["state"] == "no_email" and login_mail.mail_state("a@mail.test", [])["state"] == "not_sent"
    queued = MailOutbox(to="A@Mail.test", subject="s", body="b", kind="exam_login", status="queued")
    assert login_mail.mail_state("a@mail.test", [queued])["state"] == "queued"                          # the same address in another case is the same address


def test_only_those_who_manage_participants_may_send_or_edit_but_staff_may_read_the_record(client, smtp):
    creator, recruiter = _creator(client), _recruiter(client)
    evaluator = _login(client, "evaluator@globx.co.in", PW["evaluator@globx.co.in"])
    tid, _ = _published_exam(client, creator, "Roles mail exam")
    p = _people(client, recruiter, tid, "Rolf Roles, rolf.roles@mail.test")["Rolf Roles"]
    aid = p["assignment_id"]
    assert client.post(f"{API}/tests/{tid}/send-logins", headers=evaluator, json={}).status_code == 403
    assert client.post(f"{API}/assignments/{aid}/send-login", headers=evaluator).status_code == 403
    assert client.put(f"{API}/assignments/{aid}/participant", headers=evaluator, json={"name": "X", "email": "x@mail.test"}).status_code == 403
    assert client.get(f"{API}/assignments/{aid}/login-mails", headers=evaluator).status_code == 200
    cand = _login(client, p["username"], p["password"])
    assert client.get(f"{API}/assignments/{aid}/login-mails", headers=cand).status_code == 403
    assert client.put(f"{API}/assignments/{aid}/participant", headers=cand, json={"name": "X", "email": "x@mail.test"}).status_code == 403
