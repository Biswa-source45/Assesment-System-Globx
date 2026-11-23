"""Mailing a new staff user their login, and the staff Profile: name, password, and a change of e-mail that needs a code sent to the OLD address."""
import re
import smtplib
from datetime import timedelta
from email import message_from_bytes, policy

import pytest
from sqlalchemy import select
from test_exam_rules import PW, _login, _new_candidate, client  # noqa: F401  (client is a fixture)

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import AuditLog, MailOutbox, OtpCode, User, now
from app.services import mail

API = "/api/v1"
ORG = "orgadmin@globx.co.in"


class FakeSmtp:
    sent = []

    def __init__(self, host, port, timeout=0):
        pass

    def starttls(self): pass
    def login(self, user, password): pass
    def quit(self): pass
    def close(self): pass

    def send_message(self, msg):
        FakeSmtp.sent.append(message_from_bytes(msg.as_bytes(), policy=policy.default))


@pytest.fixture()
def smtp(monkeypatch):
    """A mail server that is set up (the real settings with the host filled in) and a stand-in for it."""
    FakeSmtp.sent = []
    cfg = get_settings().model_copy(update={"smtp_host": "smtp.test", "smtp_port": 587, "smtp_user": "", "smtp_password": "", "smtp_tls": False,
                                            "public_base_url": "https://exam.test", "demo_mode": False})
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)
    for name in ("app.services.mail", "app.api.staff", "app.api.auth", "app.services.user_mail"):
        monkeypatch.setattr(f"{name}.get_settings", lambda: cfg)
    return cfg


def _deliver():
    with SessionLocal() as db:
        mail.deliver_pending(db)


def _text(m):
    return m.get_body(preferencelist=("plain",)).get_content()


def _new_staff(client, h, email, roles=("recruiter",), password="Welcome2024x", name="Staff Person"):
    r = client.post(f"{API}/users", headers=h, json={"email": email, "name": name, "roles": list(roles), "password": password})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _count(kind):
    with SessionLocal() as db:
        return len(db.scalars(select(MailOutbox).where(MailOutbox.kind == kind)).all())


def _audit(action):
    with SessionLocal() as db:
        return len(db.scalars(select(AuditLog).where(AuditLog.action == action)).all())


# ---------------------------------------------------------------- the login mail
def test_the_login_is_mailed_with_the_real_password_and_the_link_and_the_password_is_not_kept(client, smtp):
    h = _login(client, ORG, PW[ORG])
    uid = _new_staff(client, h, "mail.me@globx.co.in", password="Welcome2024x", name="Mala Mailed")
    assert _count("staff_login") == 0                                                   # making the user mails nothing
    r = client.post(f"{API}/users/{uid}/send-login", headers=h, json={"password": "Welcome2024x"})
    assert r.status_code == 200 and r.json() == {"queued": True, "to": "mail.me@globx.co.in"}
    _deliver()
    sent = [m for m in FakeSmtp.sent if m["To"] == "mail.me@globx.co.in"]
    assert len(sent) == 1 and sent[0]["Subject"] == "Your KAUTILYA login"
    text, page = _text(sent[0]), sent[0].get_body(preferencelist=("html",)).get_content()
    for part in ("Mala Mailed", "mail.me@globx.co.in", "Welcome2024x", "Recruiter", "https://exam.test/login", "My profile"):
        assert part in text and part in page, part
    with SessionLocal() as db:
        row = db.scalar(select(MailOutbox).where(MailOutbox.kind == "staff_login"))
        assert row.status == "sent" and "Welcome2024x" not in row.body and row.body_html is None   # the outbox keeps the record, not the password
    assert _audit("login_sent") >= 1


def test_a_wrong_password_or_no_mail_server_sends_nothing(client, smtp, monkeypatch):
    h = _login(client, ORG, PW[ORG])
    uid = _new_staff(client, h, "wrong.pw@globx.co.in")
    before = _count("staff_login")
    r = client.post(f"{API}/users/{uid}/send-login", headers=h, json={"password": "Something9else"})
    assert r.status_code == 422 and "not this person's current password" in r.json()["detail"]
    assert client.put(f"{API}/users/{uid}", headers=h, json={"password": "BrandNew2024y"}).status_code == 200       # a new password was made after the first one
    assert client.post(f"{API}/users/{uid}/send-login", headers=h, json={"password": "Welcome2024x"}).status_code == 422
    assert client.post(f"{API}/users/{uid}/send-login", headers=h, json={"password": "BrandNew2024y"}).status_code == 200
    assert _count("staff_login") == before + 1
    monkeypatch.setattr("app.api.staff.get_settings", lambda: smtp.model_copy(update={"smtp_host": ""}))
    r = client.post(f"{API}/users/{uid}/send-login", headers=h, json={"password": "BrandNew2024y"})
    assert r.status_code == 422 and "E-mail is not set up" in r.json()["detail"] and _count("staff_login") == before + 1


def test_who_may_mail_a_login(client, smtp):
    h = _login(client, ORG, PW[ORG])
    uid = _new_staff(client, h, "who.may@globx.co.in")
    rec = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    assert client.post(f"{API}/users/{uid}/send-login", headers=rec, json={"password": "Welcome2024x"}).status_code == 403     # only administrators
    sup = next(u for u in client.get(f"{API}/users", headers=h, params={"role": "super_admin"}).json() if "super_admin" in u["roles"])
    assert client.post(f"{API}/users/{sup['id']}/send-login", headers=h, json={"password": "x"}).status_code == 403             # an Org Admin cannot mail a Super Admin
    cand = client.get(f"{API}/users", headers=h, params={"role": "candidate"}).json()[0]
    assert client.post(f"{API}/users/{cand['id']}/send-login", headers=h, json={"password": "x"}).status_code == 422
    assert client.post(f"{API}/users/nobody/send-login", headers=h, json={"password": "x"}).status_code == 404


def test_an_administrator_changes_their_own_email_only_through_the_profile_code(client):
    h = _login(client, ORG, PW[ORG])
    me = client.get(f"{API}/auth/me", headers=h).json()
    r = client.put(f"{API}/users/{me['id']}", headers=h, json={"name": me["name"], "email": "not.me@globx.co.in", "roles": me["roles"]})
    assert r.status_code == 409 and "My profile" in r.json()["detail"]
    assert client.get(f"{API}/auth/me", headers=h).json()["email"] == ORG


# ---------------------------------------------------------------- the profile
def test_the_profile_shows_and_changes_the_name_and_the_password(client):
    h = _login(client, ORG, PW[ORG])
    uid = _new_staff(client, h, "prof.ile@globx.co.in", password="Welcome2024x")
    me = _login(client, "prof.ile@globx.co.in", "Welcome2024x")
    got = client.get(f"{API}/auth/me", headers=me).json()
    assert got["email"] == "prof.ile@globx.co.in" and got["roles"] == ["recruiter"] and got["org_name"] and got["last_login_at"]
    assert client.put(f"{API}/auth/profile", headers=me, json={"name": "   "}).status_code == 422
    assert client.put(f"{API}/auth/profile", headers=me, json={"name": "x" * 121}).status_code == 422
    assert client.put(f"{API}/auth/profile", headers=me, json={"name": "  Prof   Ile  "}).json()["name"] == "Prof Ile"          # spaces tidied
    assert client.get(f"{API}/users", headers=h, params={"q": "prof.ile"}).json()[0]["name"] == "Prof Ile"
    assert client.post(f"{API}/auth/password", headers=me, json={"current_password": "wrong", "new_password": "Another2024z"}).status_code == 400
    assert client.post(f"{API}/auth/password", headers=me, json={"current_password": "Welcome2024x", "new_password": "short"}).status_code == 400
    assert client.post(f"{API}/auth/password", headers=me, json={"current_password": "Welcome2024x", "new_password": "Another2024z"}).status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": "prof.ile@globx.co.in", "password": "Welcome2024x"}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"email": "prof.ile@globx.co.in", "password": "Another2024z"}).status_code == 200
    assert uid


# ---------------------------------------------------------------- the change of e-mail
def _code_sent_to(address):
    _deliver()
    mails = [m for m in FakeSmtp.sent if m["To"] == address and "code" in m["Subject"]]
    assert mails, [m["To"] for m in FakeSmtp.sent]
    return re.search(r"Your code: (\d{6})", _text(mails[-1])).group(1)


def test_the_email_changes_only_with_the_code_sent_to_the_old_address(client, smtp):
    h = _login(client, ORG, PW[ORG])
    _new_staff(client, h, "old.mail@globx.co.in", password="Welcome2024x", name="Olga Old")
    _new_staff(client, h, "taken@globx.co.in", name="Taken Person")
    me = _login(client, "old.mail@globx.co.in", "Welcome2024x")
    ask = lambda new: client.post(f"{API}/auth/email-change/request", headers=me, json={"new_email": new})  # noqa: E731
    assert ask("bad address").status_code == 422 and ask("OLD.mail@globx.co.in").status_code == 422        # not an address; already yours
    assert ask("taken@globx.co.in").status_code == 409                                                     # somebody else's
    assert _count("email_change") == 0                                                                     # none of those sent a code
    r = ask("New.Mail@globx.co.in")
    assert r.status_code == 200 and r.json()["to"] == "o***l@globx.co.in" and "demo_otp" not in r.json()
    assert ask("another@globx.co.in").status_code == 429                                                   # one code a minute
    code = _code_sent_to("old.mail@globx.co.in")                                                           # the code went to the OLD address
    assert not [m for m in FakeSmtp.sent if m["To"] == "new.mail@globx.co.in"]                             # and nothing to the new one
    assert client.get(f"{API}/auth/me", headers=me).json()["email"] == "old.mail@globx.co.in"              # nothing changed yet
    wrong = "000000" if code != "000000" else "111111"
    r = client.post(f"{API}/auth/email-change/confirm", headers=me, json={"code": wrong})
    assert r.status_code == 400 and "4 attempts left" in r.json()["detail"]
    done = client.post(f"{API}/auth/email-change/confirm", headers=me, json={"code": code})
    assert done.status_code == 200 and done.json()["email"] == "new.mail@globx.co.in"                       # the address the code was made for, in lower case
    assert client.get(f"{API}/auth/me", headers=me).json()["email"] == "new.mail@globx.co.in"
    assert client.post(f"{API}/auth/login", json={"email": "new.mail@globx.co.in", "password": "Welcome2024x"}).status_code == 200
    assert client.post(f"{API}/auth/login", json={"email": "old.mail@globx.co.in", "password": "Welcome2024x"}).status_code == 401
    _deliver()
    assert [m for m in FakeSmtp.sent if m["To"] == "old.mail@globx.co.in" and "was changed" in m["Subject"]]   # the old address is told
    assert client.post(f"{API}/auth/email-change/confirm", headers=me, json={"code": code}).status_code == 410  # a used code is dead
    assert _audit("email_changed") >= 1 and _audit("email_change_requested") >= 1


def test_a_code_expires_and_locks_after_five_wrong_tries(client, smtp):
    h = _login(client, ORG, PW[ORG])
    _new_staff(client, h, "lock.me@globx.co.in", password="Welcome2024x")
    me = _login(client, "lock.me@globx.co.in", "Welcome2024x")
    assert client.post(f"{API}/auth/email-change/confirm", headers=me, json={"code": "123456"}).status_code == 410   # none asked for
    assert client.post(f"{API}/auth/email-change/request", headers=me, json={"new_email": "locked.new@globx.co.in"}).status_code == 200
    code = _code_sent_to("lock.me@globx.co.in")
    wrong = "000000" if code != "000000" else "111111"
    for left in (4, 3, 2, 1, 0):
        r = client.post(f"{API}/auth/email-change/confirm", headers=me, json={"code": wrong})
        assert r.status_code == 400 and f"{left} attempts left" in r.json()["detail"]
    assert client.post(f"{API}/auth/email-change/confirm", headers=me, json={"code": code}).status_code == 429       # locked, even for the right code
    assert client.get(f"{API}/auth/me", headers=me).json()["email"] == "lock.me@globx.co.in"
    with SessionLocal() as db:                                                                                    # a code that is old is refused
        for o in db.scalars(select(OtpCode).where(OtpCode.email == "lock.me@globx.co.in")).all():
            o.attempts, o.expires_at = 0, now() - timedelta(minutes=1)
        db.commit()
    assert client.post(f"{API}/auth/email-change/confirm", headers=me, json={"code": code}).status_code == 410


def test_no_mail_server_no_code_in_production_and_the_code_in_demo_mode(client, smtp, monkeypatch):
    h = _login(client, ORG, PW[ORG])
    _new_staff(client, h, "no.smtp@globx.co.in", password="Welcome2024x")
    me = _login(client, "no.smtp@globx.co.in", "Welcome2024x")
    monkeypatch.setattr("app.api.auth.get_settings", lambda: smtp.model_copy(update={"smtp_host": ""}))
    r = client.post(f"{API}/auth/email-change/request", headers=me, json={"new_email": "no.smtp.new@globx.co.in"})
    assert r.status_code == 422 and "E-mail is not set up" in r.json()["detail"]
    monkeypatch.setattr("app.api.auth.get_settings", lambda: smtp.model_copy(update={"smtp_host": "", "demo_mode": True}))
    r = client.post(f"{API}/auth/email-change/request", headers=me, json={"new_email": "no.smtp.new@globx.co.in"})
    assert r.status_code == 200 and re.fullmatch(r"\d{6}", r.json()["demo_otp"])


def test_an_email_change_code_never_signs_anybody_in_and_a_candidate_has_no_email_change(client, smtp):
    h = _login(client, ORG, PW[ORG])
    _new_staff(client, h, "guard.me@globx.co.in", password="Welcome2024x")
    me = _login(client, "guard.me@globx.co.in", "Welcome2024x")
    assert client.post(f"{API}/auth/email-change/request", headers=me, json={"new_email": "guard.new@globx.co.in"}).status_code == 200
    code = _code_sent_to("guard.me@globx.co.in")
    assert client.post(f"{API}/auth/otp/verify", json={"email": "guard.me@globx.co.in", "otp": code}).status_code == 410    # the candidate sign-in does not see it
    with SessionLocal() as db:                                                                                    # even a sign-in code for a staff address signs nobody in
        from app.core.security import hash_otp
        db.add(OtpCode(email="guard.me@globx.co.in", code_hash=hash_otp("guard.me@globx.co.in", "424242"), expires_at=now() + timedelta(minutes=5)))
        db.commit()
    assert client.post(f"{API}/auth/otp/verify", json={"email": "guard.me@globx.co.in", "otp": "424242"}).status_code == 403
    _, cand, _ = _new_candidate(client, "Gita Guard")
    assert client.post(f"{API}/auth/email-change/request", headers=cand, json={"new_email": "x@y.co"}).status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "guard.me@globx.co.in")) is not None
