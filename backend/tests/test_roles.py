"""Who may do what (the role matrix) and user management. Shares its fixture and helpers with test_exam_rules (seeded database, staff logins)."""
from test_exam_rules import PW, _login, _new_candidate, client  # noqa: F401  (client is a fixture)

API = "/api/v1"
WHO = {"super_admin": "superadmin@globx.co.in", "org_admin": "orgadmin@globx.co.in", "test_creator": "creator@globx.co.in",
       "recruiter": "recruiter@globx.co.in", "evaluator": "evaluator@globx.co.in"}
ALL = set(WHO)
# action: (method, path, body, the roles that may do it). A denied role gets 403; an allowed one gets anything else (404 for the made-up id, 422 for the empty body).
MATRIX = {
    "see the exam list": ("get", "/tests", None, ALL),
    "create an exam": ("post", "/tests", {}, {"super_admin", "org_admin", "test_creator"}),
    "read the question bank": ("get", "/questions", None, {"super_admin", "org_admin", "test_creator", "evaluator"}),
    "create a question": ("post", "/questions", {}, {"super_admin", "org_admin", "test_creator"}),
    "create a department": ("post", "/departments", {}, {"super_admin", "org_admin", "test_creator"}),
    "add participants": ("post", "/tests/none/participants", {"names": []}, {"super_admin", "org_admin", "test_creator", "recruiter"}),
    "watch the live monitor": ("get", "/tests/none/monitor", None, ALL),
    "mark answers": ("post", "/answers/none/evaluate", {}, {"super_admin", "org_admin", "evaluator"}),
    "manage users": ("get", "/users", None, {"super_admin", "org_admin"}),
    "read the audit log": ("get", "/system/audit", None, {"super_admin", "org_admin"}),
    "manage organisations": ("get", "/orgs", None, {"super_admin"}),
}


def _as(client, role):
    return _login(client, WHO[role], PW[WHO[role]])


def test_role_matrix_is_enforced_by_the_server(client):
    for role in WHO:
        h = _as(client, role)
        for action, (method, path, body, allowed) in MATRIX.items():
            r = client.request(method, API + path, headers=h, json=body)
            assert (r.status_code != 403) == (role in allowed), f"{role} / {action}: got {r.status_code}"
    _, cand, _ = _new_candidate(client, "Matrix Candidate")
    for action, (method, path, body, _) in MATRIX.items():
        assert client.request(method, API + path, headers=cand, json=body).status_code == 403, f"candidate / {action}"  # a candidate may do none of it
        assert client.request(method, API + path, json=body).status_code == 401, f"signed out / {action}"


def test_the_browser_is_told_exactly_what_the_server_allows(client):
    expect = {"recruiter": {"author": False, "recruit": True, "view": True, "bank": False, "evaluate": False, "admin": False, "super": False},
              "evaluator": {"author": False, "recruit": False, "view": True, "bank": True, "evaluate": True, "admin": False, "super": False},
              "test_creator": {"author": True, "recruit": True, "view": True, "bank": True, "evaluate": False, "admin": False, "super": False},
              "org_admin": {"author": True, "recruit": True, "view": True, "bank": True, "evaluate": True, "admin": True, "super": False},
              "super_admin": {"author": True, "recruit": True, "view": True, "bank": True, "evaluate": True, "admin": True, "super": True}}
    for role, can in expect.items():
        assert client.get(f"{API}/auth/me", headers=_as(client, role)).json()["can"] == can, role


def _user(client, h, **kw):
    body = {"email": "new.person@globx.co.in", "name": "New Person", "roles": ["recruiter"], "password": "Start1234", **kw}
    return client.post(f"{API}/users", headers=h, json=body)


def test_creating_and_editing_users(client):
    sup, org = _as(client, "super_admin"), _as(client, "org_admin")
    made = _user(client, org, email="New.Person@Globx.co.in")
    assert made.status_code == 200, made.text
    u = made.json()
    assert u["email"] == "new.person@globx.co.in" and u["roles"] == ["recruiter"] and u["status"] == "active"
    assert _user(client, org).status_code == 409                                         # same email
    assert _user(client, org, email="x.globx.co.in").status_code == 422                  # not an email address
    assert _user(client, org, email="a@globx.co.in", roles=[]).status_code == 422        # no role
    assert _user(client, org, email="a@globx.co.in", roles=["candidate"]).status_code == 422  # staff only: candidates get logins from their exam
    assert _user(client, org, email="a@globx.co.in", password="short").status_code == 422
    assert _user(client, org, email="a@globx.co.in", name=" ").status_code == 422
    assert _user(client, org, email="boss@globx.co.in", roles=["super_admin"]).status_code == 403  # only a Super Admin grants Super Admin
    assert _user(client, sup, email="boss@globx.co.in", name="Second Boss", roles=["super_admin"]).status_code == 200
    assert u["id"] in [x["id"] for x in client.get(f"{API}/users", headers=org).json()]
    assert [x["id"] for x in client.get(f"{API}/users?role=recruiter", headers=org).json()].count(u["id"]) == 1

    edit = client.put(f"{API}/users/{u['id']}", headers=org, json={"name": "Renamed Person", "email": "renamed@globx.co.in", "roles": ["evaluator", "test_creator"]}).json()
    assert (edit["name"], edit["email"], edit["roles"], edit["status"]) == ("Renamed Person", "renamed@globx.co.in", ["evaluator", "test_creator"], "active")
    assert client.put(f"{API}/users/{u['id']}", headers=org, json={"email": "orgadmin@globx.co.in"}).status_code == 409   # another person's email
    assert client.put(f"{API}/users/{u['id']}", headers=org, json={"roles": ["super_admin"]}).status_code == 403
    assert client.put(f"{API}/users/none", headers=org, json={"name": "x"}).status_code == 404
    assert client.put(f"{API}/users/{u['id']}", headers=_as(client, "recruiter"), json={"name": "x"}).status_code == 403
    assert client.get(f"{API}/users", headers=_as(client, "recruiter")).status_code == 403


def test_a_new_password_or_a_disabled_account_ends_open_sessions_and_unlock_works(client):
    org = _as(client, "org_admin")
    u = _user(client, org, email="session.person@globx.co.in", name="Session Person").json()
    login = lambda pw: client.post(f"{API}/auth/login", json={"email": "session.person@globx.co.in", "password": pw})
    first = login("Start1234").json()
    assert client.put(f"{API}/users/{u['id']}", headers=org, json={"password": "weak"}).status_code == 422

    assert client.put(f"{API}/users/{u['id']}", headers=org, json={"password": "Fresh5678"}).status_code == 200
    assert client.post(f"{API}/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401  # the old session cannot continue
    assert login("Start1234").status_code == 401 and login("Fresh5678").status_code == 200

    me = {"Authorization": "Bearer " + login("Fresh5678").json()["access_token"]}
    assert client.put(f"{API}/users/{u['id']}", headers=org, json={"status": "disabled"}).json()["status"] == "disabled"
    assert client.get(f"{API}/auth/me", headers=me).status_code == 401           # a disabled person is out at once, even with a valid token
    assert login("Fresh5678").status_code == 403
    assert client.put(f"{API}/users/{u['id']}", headers=org, json={"name": "Still Disabled"}).json()["status"] == "disabled"  # an edit does not re-enable
    assert client.put(f"{API}/users/{u['id']}", headers=org, json={"status": "active"}).json()["status"] == "active"
    assert login("Fresh5678").status_code == 200

    for _ in range(10):
        login("wrong-pass1")
    assert login("Fresh5678").status_code == 423                                   # locked after ten failures
    row = next(x for x in client.get(f"{API}/users", headers=org).json() if x["id"] == u["id"])
    assert row["locked"] is True
    assert client.put(f"{API}/users/{u['id']}", headers=org, json={"name": "Session Person", "unlock": True}).json()["locked"] is False
    assert login("Fresh5678").status_code == 200


def test_who_can_change_whom(client):
    org, sup = _as(client, "org_admin"), _as(client, "super_admin")
    users = {x["email"]: x for x in client.get(f"{API}/users", headers=sup).json()}
    boss = users["superadmin@globx.co.in"]
    assert client.put(f"{API}/users/{boss['id']}", headers=org, json={"password": "Hijack1234"}).status_code == 403   # an Org Admin cannot touch a Super Admin
    assert client.put(f"{API}/users/{boss['id']}", headers=org, json={"status": "disabled"}).status_code == 403
    me = users["orgadmin@globx.co.in"]
    assert client.put(f"{API}/users/{me['id']}", headers=org, json={"status": "disabled"}).status_code == 409          # not yourself
    assert client.put(f"{API}/users/{me['id']}", headers=org, json={"roles": ["recruiter"]}).status_code == 409         # nor your own admin access
    assert client.put(f"{API}/users/{me['id']}", headers=org, json={"name": "Org Admin", "roles": ["org_admin", "recruiter"]}).status_code == 200
    assert client.put(f"{API}/users/{boss['id']}", headers=sup, json={"status": "disabled"}).status_code == 409          # a Super Admin cannot lock themselves out either


def test_candidates_are_listed_with_their_exams_and_can_get_a_new_password(client):
    org = _as(client, "org_admin")
    _, cand, aid = _new_candidate(client, "Listed Candidate")
    rows = client.get(f"{API}/users?role=candidate", headers=org).json()
    row = next(x for x in rows if x["name"] == "Listed Candidate")
    assert row["username"].startswith("listed") and row["roles"] == ["candidate"] and row["exams"] == ["GLOBX Full-Stack Screening (Sample)"]
    assert "Listed Candidate" not in [x["name"] for x in client.get(f"{API}/users", headers=org).json()]   # the default list is staff
    r = client.put(f"{API}/users/{row['id']}", headers=org, json={"password": "Candidate123", "roles": ["org_admin"]})  # roles cannot be changed on a candidate
    assert r.status_code == 200 and r.json()["roles"] == ["candidate"]
    assert client.post(f"{API}/auth/login", json={"email": row["username"], "password": "Candidate123"}).status_code == 200
