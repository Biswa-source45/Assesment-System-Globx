"""Live view and voice (the relay), the whole-exam video upload, and its deletion after the retention days. Shares its fixture with test_exam_rules."""
import os
import time
from datetime import timedelta

import pytest
from starlette.websockets import WebSocketDisconnect
from test_exam_rules import DEPT, PW, _event, _login, _start, client  # noqa: F401  (client is a fixture)

from app.core.config import get_settings
from app.db import SessionLocal
from app.models import Attempt, Recording, now
from app.services.proctoring import purge_recordings

API = "/api/v1"
VIDEO = {"live_view": True, "evidence": "video", "screen_share": True, "video_retention_days": 14}


def _exam(client, h, title, proctoring):
    q = client.post(f"{API}/questions", headers=h, json={"department_id": DEPT["Technical"], "type": "mcq_single", "title": f"{title} q", "body": "<p>x</p>", "marks": 1,
                                                          "config": {"options": [{"id": "a", "text": "A", "correct": True}, {"id": "b", "text": "B", "correct": False}]}}).json()
    t = client.post(f"{API}/tests", headers=h, json={"department_id": DEPT["Technical"], "title": title, "duration_min": 30, "settings": {"proctoring": proctoring}}).json()
    sid = client.post(f"{API}/tests/{t['id']}/sections", headers=h, json={"title": "All"}).json()["sections"][0]["id"]
    client.post(f"{API}/sections/{sid}/items", headers=h, json={"kind": "question", "question_id": q["id"]})
    assert client.post(f"{API}/tests/{t['id']}/publish", headers=h).status_code == 200
    return t["id"]


def _person(client, h, tid, name):
    p = client.post(f"{API}/tests/{tid}/participants", headers=h, json={"names": [name]}).json()["participants"][0]
    cand = _login(client, p["username"], p["password"])
    return cand, _start(client, cand, p["assignment_id"]), p["assignment_id"]


def _token(headers):
    return headers["Authorization"].split()[1]


def _ws(client, tid, headers):
    return client.websocket_connect(f"{API}/live/{tid}?access_token={_token(headers)}")


def _counts(client, h, at, **expected):
    """The attempt's event counts; with `expected`, wait (the log is written a moment after the line changes) until they hold."""
    for _ in range(40):
        counts = client.get(f"{API}/reports/attempts/{at}", headers=h).json()["proctoring"]["counts"]
        if all(counts.get(k, 0) == v for k, v in expected.items()):
            break
        time.sleep(0.1)
    return counts


def test_the_exam_settings_are_read_the_way_the_server_decides(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    tid = _exam(client, creator, "Settings exam", {"evidence": "bogus", "video_retention_days": 9999, "screenshot_seconds": 1, "live_view": 1, "screen_share": "yes"})
    p = client.post(f"{API}/tests/{tid}/participants", headers=creator, json={"names": ["Cfg Check"]}).json()["participants"][0]
    cand = _login(client, p["username"], p["password"])
    cfg = next(a for a in client.get(f"{API}/me/assignments", headers=cand).json() if a["assignment_id"] == p["assignment_id"])["test"]["proctoring"]
    assert (cfg["evidence"], cfg["video_retention_days"], cfg["screenshot_seconds"], cfg["live_view"], cfg["screen_share"]) == ("pictures", 90, 10, True, True)  # a bad value never gets through: too long is cut to the 90-day maximum, too short to 10 s
    plain = _exam(client, creator, "Plain exam", {})
    p = client.post(f"{API}/tests/{plain}/participants", headers=creator, json={"names": ["Default Check"]}).json()["participants"][0]
    cfg = next(a for a in client.get(f"{API}/me/assignments", headers=_login(client, p["username"], p["password"])).json() if a["assignment_id"] == p["assignment_id"])["test"]["proctoring"]
    assert (cfg["evidence"], cfg["live_view"], cfg["screen_share"], cfg["video_retention_days"], cfg["screenshot_seconds"]) == ("pictures", False, False, 14, 60)


def test_stopping_the_screen_share_counts_like_leaving_the_exam(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    tid = _exam(client, creator, "Share stop exam", {"screen_share": True})
    cand, at, _ = _person(client, creator, tid, "Stop Sharer")
    for i in (1, 2, 3):
        out = _event(client, cand, at, type="screen_share_stopped")
        assert out["action"] == "warn" and out["violations"] == i and "screen share" in out["message"]
    assert _event(client, cand, at, type="screen_share_stopped")["action"] == "force_submit"  # the fourth ends the exam, as a tab leave does


def test_only_the_right_people_can_join_the_live_room(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    evaluator = _login(client, "evaluator@globx.co.in", PW["evaluator@globx.co.in"])
    tid = _exam(client, creator, "Room exam", VIDEO)
    off = _exam(client, creator, "No live exam", {})
    cand, at, _ = _person(client, creator, tid, "Room Member")
    other, _, _ = _person(client, creator, off, "No Live Member")
    for who, exam in ((evaluator, tid), (other, tid), (cand, off), ({"Authorization": "Bearer nonsense"}, tid)):
        with pytest.raises(WebSocketDisconnect):
            with _ws(client, exam, who):
                pass  # an evaluator, a candidate of another exam, a candidate of an exam without live view, a bad token: all refused
    with _ws(client, tid, creator) as examiner:
        assert examiner.receive_json()["peers"] == []
    client.post(f"{API}/attempts/{at}/submit", headers=cand, json={})
    with pytest.raises(WebSocketDisconnect):
        with _ws(client, tid, cand):
            pass  # a candidate whose exam is over


def test_the_relay_connects_talks_and_messages_one_candidate_and_logs_it(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    tid = _exam(client, creator, "Relay exam", VIDEO)
    asha, at_a, _ = _person(client, creator, tid, "Asha Talked")
    bala, at_b, _ = _person(client, creator, tid, "Bala Quiet")

    with _ws(client, tid, creator) as examiner:
        hello = examiner.receive_json()
        me = hello["you"]
        assert hello["peers"] == [] and hello["talking"] == {}
        with _ws(client, tid, asha) as cand_a, _ws(client, tid, bala) as cand_b:
            assert cand_a.receive_json() == {"type": "examiners", "ids": [me]}      # a candidate is told who to send its camera and screen to
            assert cand_b.receive_json() == {"type": "examiners", "ids": [me]}
            assert {examiner.receive_json()["id"] for _ in range(2)} == {at_a, at_b}

            cand_a.send_json({"type": "offer", "to": me, "sdp": "v=0 offer", "streams": {"camera": "c1", "screen": "s1"}, "junk": "dropped"})
            offer = examiner.receive_json()
            assert offer == {"type": "offer", "from": at_a, "sdp": "v=0 offer", "streams": {"camera": "c1", "screen": "s1"}}  # only what two browsers need
            examiner.send_json({"type": "answer", "to": at_a, "sdp": "v=0 answer"})
            assert cand_a.receive_json()["sdp"] == "v=0 answer"
            examiner.send_json({"type": "ice", "to": at_a, "candidate": {"c": 1}})
            assert cand_a.receive_json()["candidate"] == {"c": 1}

            cand_a.send_json({"type": "talk-start", "to": me})                       # a candidate cannot start a line, nor reach another candidate
            cand_a.send_json({"type": "offer", "to": at_b, "sdp": "x"})

            examiner.send_json({"type": "talk-start", "to": at_a})                   # the examiner talks to Asha only
            assert cand_a.receive_json() == {"type": "talk-start", "from": me}
            assert examiner.receive_json() == {"type": "talking", "id": at_a, "by": me}
            with _ws(client, tid, recruiter) as second:                              # a second examiner joins and finds the line busy
                other = second.receive_json()
                assert other["talking"] == {at_a: me} and {p["id"] for p in other["peers"]} == {at_a, at_b}
                assert cand_a.receive_json()["type"] == "examiner" and cand_b.receive_json()["type"] == "examiner"
                second.send_json({"type": "talk-start", "to": at_a})
                assert second.receive_json() == {"type": "busy", "id": at_a}
            assert cand_a.receive_json()["type"] == "examiner-left" and cand_b.receive_json()["type"] == "examiner-left"

            examiner.send_json({"type": "message", "to": at_b, "text": "  Please look at your own screen.  "})
            assert cand_b.receive_json() == {"type": "message", "from": me, "text": "Please look at your own screen."}
            examiner.send_json({"type": "message", "to": at_b, "text": "x" * 900})
            assert len(cand_b.receive_json()["text"]) == 500
            examiner.send_json({"type": "message", "to": at_b, "text": "   "})      # nothing to say: nothing sent

            examiner.send_json({"type": "talk-stop", "to": at_a})
            assert cand_a.receive_json() == {"type": "talk-stop", "from": me}
            assert examiner.receive_json() == {"type": "talking", "id": at_a, "by": None}

            examiner.send_json({"type": "talk-start", "to": at_b})                   # a line open when the examiner's connection drops is closed
            assert cand_b.receive_json()["type"] == "talk-start"
        # both candidates disconnected here
    counts_a = _counts(client, creator, at_a, talk_started=1, talk_ended=1)
    assert counts_a["talk_started"] == 1 and counts_a["talk_ended"] == 1 and "message_sent" not in counts_a
    counts_b = _counts(client, creator, at_b, message_sent=2, talk_ended=1)
    assert counts_b["message_sent"] == 2 and counts_b["talk_ended"] == 1  # the open line was ended and logged


def test_an_examiner_leaving_ends_the_line_and_tells_the_candidate(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    tid = _exam(client, creator, "Leave exam", VIDEO)
    cand, at, _ = _person(client, creator, tid, "Left Hanging")
    with _ws(client, tid, cand) as c:
        assert c.receive_json()["ids"] == []
        with _ws(client, tid, creator) as examiner:
            me = examiner.receive_json()["you"]
            assert c.receive_json() == {"type": "examiner", "id": me}
            examiner.send_json({"type": "talk-start", "to": at})
            assert c.receive_json()["type"] == "talk-start"
        assert c.receive_json()["type"] == "talk-stop"             # the line is closed for the candidate...
        assert c.receive_json() == {"type": "examiner-left", "id": me}  # ...and the candidate learns the examiner is gone
    assert _counts(client, creator, at, talk_ended=1)["talk_ended"] == 1


def _piece(client, headers, at, kind, part, seq, data):
    return client.post(f"{API}/attempts/{at}/recording/{kind}", headers=headers, params={"part": part, "seq": seq}, files={"piece": ("p.webm", data, "video/webm")})


def test_video_pieces_are_stored_in_order_without_repeats_and_only_where_the_exam_records(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    evaluator = _login(client, "evaluator@globx.co.in", PW["evaluator@globx.co.in"])
    tid = _exam(client, creator, "Video exam", VIDEO)
    cand, at, _ = _person(client, creator, tid, "Vid Eo")
    other, other_at, _ = _person(client, creator, tid, "Other Eo")

    assert _piece(client, cand, at, "webcam", "run1", 0, b"AAA").json() == {"ok": True, "next": 1}
    assert _piece(client, cand, at, "webcam", "run1", 1, b"BBB").json()["next"] == 2
    assert _piece(client, cand, at, "webcam", "run1", 1, b"BBB").json() == {"ok": True, "duplicate": True}   # a retry after a lost answer is ignored
    assert _piece(client, cand, at, "webcam", "run1", 4, b"EEE").json()["next"] == 5                          # pieces 2 and 3 never came: a gap, not an error
    assert _piece(client, cand, at, "screen", "run1", 0, b"SSS").status_code == 200
    assert _piece(client, cand, at, "webcam", "run2", 0, b"NEW").status_code == 200                             # a page reload starts a new file

    root = get_settings().storage_dir
    assert open(os.path.join(root, "recordings", at, "webcam-run1.webm"), "rb").read() == b"AAABBBEEE"
    assert open(os.path.join(root, "recordings", at, "webcam-run2.webm"), "rb").read() == b"NEW"

    assert _piece(client, cand, at, "webcam", "bad part!", 0, b"x").status_code == 422
    assert _piece(client, cand, at, "audio", "run1", 0, b"x").status_code == 422
    assert _piece(client, cand, at, "webcam", "run1", 9, b"x" * (8 * 1024 * 1024 + 1)).status_code == 413
    assert _piece(client, other, at, "webcam", "run1", 9, b"x").status_code == 404                              # nobody else's attempt
    pictures = _exam(client, creator, "Pictures exam", {"screen_share": False})
    pcand, pat, _ = _person(client, creator, pictures, "Pic Ture")
    assert _piece(client, pcand, pat, "webcam", "run1", 0, b"x").status_code == 403                             # this exam keeps pictures, not video
    no_screen = _exam(client, creator, "No screen exam", {"evidence": "video"})
    ncand, nat, _ = _person(client, creator, no_screen, "No Screen")
    assert _piece(client, ncand, nat, "webcam", "run1", 0, b"x").status_code == 200
    assert _piece(client, ncand, nat, "screen", "run1", 0, b"x").status_code == 403                             # video of a screen nobody shares

    listing = client.get(f"{API}/attempts/{at}/recordings", headers=recruiter).json()
    assert listing["retention_days"] == 14
    run1 = next(r for r in listing["recordings"] if r["kind"] == "webcam" and r["bytes"] == 9)
    assert (run1["pieces"], run1["gaps"], run1["expired"]) == (5, 2, False)  # pieces 2 and 3 are missing
    assert client.get(f"{API}/attempts/{at}/recordings", headers=evaluator).status_code == 403                 # video is for the people who run the exam
    assert client.get(f"{API}/attempts/{at}/recordings", headers=cand).status_code == 403
    assert client.get(f"{API}/recordings/{run1['id']}/file", headers=recruiter).content == b"AAABBBEEE"
    assert client.get(f"{API}/recordings/{run1['id']}/file", headers=evaluator).status_code == 403

    # the last piece may arrive just after the submit, not long after it
    client.post(f"{API}/attempts/{at}/submit", headers=cand, json={})
    assert _piece(client, cand, at, "webcam", "run1", 5, b"Z").status_code == 200
    with SessionLocal() as db:
        db.get(Attempt, at).submitted_at = now() - timedelta(minutes=5)
        db.commit()
    assert _piece(client, cand, at, "webcam", "run1", 6, b"Z").status_code == 423


def test_video_is_deleted_after_its_exams_retention_days_and_never_before(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    tid = _exam(client, creator, "Retention exam", VIDEO)  # 14 days
    short = _exam(client, creator, "Short retention exam", {**VIDEO, "video_retention_days": 3})
    old, at_old, _ = _person(client, creator, tid, "Old Video")
    young, at_young, _ = _person(client, creator, tid, "Young Video")
    quick, at_quick, _ = _person(client, creator, short, "Quick Video")
    for c, at in ((old, at_old), (young, at_young), (quick, at_quick)):
        assert _piece(client, c, at, "webcam", "r", 0, b"VIDEO").status_code == 200
    ages = {at_old: 15, at_young: 13, at_quick: 4}  # days since the last piece
    with SessionLocal() as db:
        for r in db.query(Recording).filter(Recording.attempt_id.in_(list(ages))).all():
            r.last_at = now() - timedelta(days=ages[r.attempt_id])
        db.commit()
    path = lambda at: os.path.join(get_settings().storage_dir, "recordings", at, "webcam-r.webm")

    with SessionLocal() as db:
        assert purge_recordings(db) >= 2
    assert not os.path.exists(path(at_old)) and not os.path.exists(path(at_quick))   # 15 > 14 days, and 4 > 3 days for the exam that keeps it 3
    assert os.path.exists(path(at_young))                                            # 13 days: still kept
    rows = {r["bytes"]: r for r in client.get(f"{API}/attempts/{at_old}/recordings", headers=recruiter).json()["recordings"]}
    assert rows[5]["expired"] is True                                                # the page can say "deleted after 14 days"
    rid = client.get(f"{API}/attempts/{at_old}/recordings", headers=recruiter).json()["recordings"][0]["id"]
    assert client.get(f"{API}/recordings/{rid}/file", headers=recruiter).status_code == 404
    assert _piece(client, old, at_old, "webcam", "r", 1, b"more").status_code == 410  # nothing is added to a deleted video
    with SessionLocal() as db:
        assert purge_recordings(db) == 0                                             # nothing left to do
