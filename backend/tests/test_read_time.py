from types import SimpleNamespace

import pytest

from app.services.attempts import min_question_seconds
from test_exam_rules import _new_candidate, _start, client  # noqa: F401  (client is a fixture)
from test_results import _wait

API = "/api/v1"


@pytest.mark.parametrize("raw, want", [
    (0, 0), (5, 5), (60, 60), (61, 60), (1000, 60), (-3, 0), (2.5, 2), ("abc", 0), ("5", 0), (True, 0), (False, 0),
    (float("inf"), 0), (float("nan"), 0), ([5], 0), ({"a": 1}, 0),
])
def test_minimum_reading_time_is_a_safe_number_of_seconds(raw, want):
    assert min_question_seconds(SimpleNamespace(settings={"min_question_seconds": raw})) == want


def test_an_exam_with_no_value_of_its_own_gets_the_platform_default(monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "read_seconds_default", 5)
    for settings in (None, {}, {"min_question_seconds": None}, {"proctoring": {}}):
        assert min_question_seconds(SimpleNamespace(settings=settings)) == 5  # older exams, exams from upload or AI: the wait is on
    assert min_question_seconds(SimpleNamespace(settings={"min_question_seconds": 0})) == 0  # an author can still turn it off
    assert min_question_seconds(SimpleNamespace(settings={"min_question_seconds": 8})) == 8
    monkeypatch.setattr(get_settings(), "read_seconds_default", 0)
    assert min_question_seconds(SimpleNamespace(settings={})) == 0


def test_the_server_remembers_when_a_question_was_first_shown(client):
    _, cand, aid = _new_candidate(client, "Read Once")
    at = _start(client, cand, aid)
    state = client.get(f"{API}/attempts/{at}", headers=cand).json()
    assert state["seen"] == {}
    first, second = [q["id"] for s in state["sections"] for q in s["questions"]][:2]

    a = client.post(f"{API}/attempts/{at}/questions/{first}/seen", headers=cand)
    assert a.status_code == 200 and a.json()["seen_at"] <= a.json()["server_time"]
    b = client.post(f"{API}/attempts/{at}/questions/{second}/seen", headers=cand)
    again = client.post(f"{API}/attempts/{at}/questions/{first}/seen", headers=cand)
    assert again.json()["seen_at"] == a.json()["seen_at"]  # the first time stays: coming back never starts a new wait
    seen = client.get(f"{API}/attempts/{at}", headers=cand).json()["seen"]
    assert seen == {first: a.json()["seen_at"], second: b.json()["seen_at"]}  # both are kept, none overwrote the other

    assert client.post(f"{API}/attempts/{at}/questions/not-a-question/seen", headers=cand).status_code == 404
    _, other, _ = _new_candidate(client, "Read Other")
    assert client.post(f"{API}/attempts/{at}/questions/{first}/seen", headers=other).status_code == 404  # not their attempt

    assert client.post(f"{API}/attempts/{at}/submit", headers=cand, json={}).status_code == 200
    assert client.post(f"{API}/attempts/{at}/questions/{first}/seen", headers=cand).status_code == 423  # nothing changes after submitting
    _wait(lambda: client.get(f"{API}/attempts/{at}", headers=cand).json()["attempt"]["status"] in ("review_pending", "evaluated"), "marking")  # let the background marking finish
