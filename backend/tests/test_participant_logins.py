"""Exam logins: a readable username and password made from the person's name, an optional email, login by either, and no half-made lists.
Shares its fixture and helpers with the other exam tests."""
import re

from test_exam_pack import _creator, _exam
from test_exam_rules import PW, _login, client  # noqa: F401  (client is a fixture)

from app.db import SessionLocal
from app.models import User
from sqlalchemy import func, select

API = "/api/v1"


def _add(client, h, tid, *lines):
    return client.post(f"{API}/tests/{tid}/participants", headers=h, json={"names": list(lines)})


def _sign_in(client, who, password):
    return client.post(f"{API}/auth/login", json={"email": who, "password": password}).status_code


def _count(name_part):
    with SessionLocal() as db:
        return db.scalar(select(func.count(User.id)).where(User.name.ilike(f"%{name_part}%")))


def test_the_username_and_password_are_made_from_the_name(client):
    h = _creator(client)
    tid = _exam(client, h, title="Names exam")["id"]
    got = _add(client, h, tid, "Zara Rao", "Zara Das", "Zara Khan", "Jo", "D'Souza Maria", "12345", "  ").json()["participants"]
    by_name = {p["name"]: p for p in got}
    assert len(got) == 6                                                           # the blank line is skipped, nothing else
    assert [by_name[n]["username"] for n in ("Zara Rao", "Zara Das", "Zara Khan")] == ["zara", "zara2", "zara3"]
    for n in ("Zara Rao", "Zara Das", "Zara Khan"):
        assert re.fullmatch(r"zar@globx\d{3}", by_name[n]["password"]), by_name[n]
    assert re.fullmatch(r"jo@globx\d{3}", by_name["Jo"]["password"])                 # a short name is used as it is
    assert by_name["D'Souza Maria"]["username"] == "dsouza" and re.fullmatch(r"dso@globx\d{3}", by_name["D'Souza Maria"]["password"])
    assert by_name["12345"]["username"] == "12345" and re.fullmatch(r"123@globx\d{3}", by_name["12345"]["password"])
    for p in got:
        assert _sign_in(client, p["username"], p["password"]) == 200, p                 # every printed login really works

    again = _add(client, h, tid, "Zara Late").json()["participants"][0]                # a later batch carries on from the same names
    assert again["username"] == "zara4"
    nothing = _add(client, h, tid, "%%%", "!!").json()["participants"]                 # no letters at all: still a usable login
    assert [p["username"] for p in nothing] == ["cand", "cand2"] and all(re.fullmatch(r"can@globx\d{3}", p["password"]) for p in nothing)


def test_a_person_signs_in_with_the_username_or_the_email_however_it_is_typed(client):
    h = _creator(client)
    tid = _exam(client, h, title="Sign in exam")["id"]
    p = _add(client, h, tid, "Ravi Kumar, Ravi.Kumar@Example.com").json()["participants"][0]
    assert p["username"] == "ravi" and re.fullmatch(r"rav@globx\d{3}", p["password"])
    pw = p["password"]
    for who in ("ravi", "RAVI", " Ravi ", "ravi.kumar@example.com", "RAVI.KUMAR@EXAMPLE.COM"):
        assert _sign_in(client, who, pw) == 200, who
    assert _sign_in(client, "ravi", pw + " ") == 200 and _sign_in(client, "ravi", " " + pw) == 200  # a space pasted with the password does not matter
    assert _sign_in(client, "ravi", pw.upper()) == 401 and _sign_in(client, "ravi", "wrong") == 401  # but the password itself is exact
    with SessionLocal() as db:
        assert db.scalar(select(User.email).where(User.username == "ravi")) == "ravi.kumar@example.com"


def test_email_is_optional_and_a_bad_list_creates_nobody(client):
    h = _creator(client)
    tid = _exam(client, h, title="Emails exam")["id"]
    ok = _add(client, h, tid, "Mia One", "Noa Two; noa.two@example.com", "Oli Three\toli.three@example.com").json()["participants"]
    assert [p["username"] for p in ok] == ["mia", "noa", "oli"]
    with SessionLocal() as db:
        emails = dict(db.execute(select(User.username, User.email).where(User.username.in_(["mia", "noa", "oli"]))).all())
    assert emails == {"mia": "mia@exam.local", "noa": "noa.two@example.com", "oli": "oli.three@example.com"}

    before = _count("Bad ")
    for why, lines, message in (
        ("not an email", ["Bad One", "Bad Two, not-an-email"], "Line 2"),
        ("repeated in the list", ["Bad Three, same@example.com", "Bad Four, SAME@example.com"], "Line 2"),
        ("a login that exists", ["Bad Five", "Bad Six, noa.two@example.com"], "Line 2"),
        ("a staff address", ["Bad Seven, superadmin@globx.co.in"], "Line 1"),
    ):
        r = _add(client, h, tid, *lines)
        assert r.status_code == 422 and message in r.text, (why, r.text)
    assert _count("Bad ") == before                                                   # not even the good lines of a bad list were made


def test_a_new_password_follows_the_same_rule_and_the_old_one_stops(client):
    h = _creator(client)
    tid = _exam(client, h, title="Fresh exam")["id"]
    first = _add(client, h, tid, "Dev Mehta").json()["participants"][0]
    one = client.post(f"{API}/assignments/{first['assignment_id']}/password", headers=h).json()
    assert one["username"] == "dev" and re.fullmatch(r"dev@globx\d{3}", one["password"])
    sheet = client.post(f"{API}/tests/{tid}/passwords", headers=h).json()["participants"]
    assert [p["username"] for p in sheet] == ["dev"] and re.fullmatch(r"dev@globx\d{3}", sheet[0]["password"])
    assert _sign_in(client, "dev", sheet[0]["password"]) == 200
    if one["password"] != sheet[0]["password"]:                                          # (the 3 digits can repeat by chance)
        assert _sign_in(client, "dev", one["password"]) == 401
