"""Two things can create the same answer row at the same moment: the candidate's last save and the closing of the exam. The loser must read the winner's row."""
from sqlalchemy import func, select
from test_exam_rules import PW, _login, _start, client  # noqa: F401  (client is a fixture)
from test_results import _exam, _finished, _person, _wait

from app.db import SessionLocal
from app.models import Answer
from app.services.attempts import _insert_answer, get_or_create_answer

API = "/api/v1"


def test_creating_an_answer_that_was_just_created_reads_it_instead_of_failing(client):
    creator = _login(client, "creator@globx.co.in", PW["creator@globx.co.in"])
    recruiter = _login(client, "recruiter@globx.co.in", PW["recruiter@globx.co.in"])
    tid, q = _exam(client, creator, "Race exam")
    cand, asg = _person(client, recruiter, tid, "Race Runner")
    at = _start(client, cand, asg)
    qid = q["mcq"]

    with SessionLocal() as winner, SessionLocal() as loser:
        won = Answer(attempt_id=at, question_id=qid, response={"selected": ["a"]})
        winner.add(won)
        winner.commit()                                   # the other side got there first
        got = _insert_answer(loser, at, qid)              # this is the moment both try to insert: it used to raise a unique violation
        assert got.id == won.id and got.response == {"selected": ["a"]}
        assert get_or_create_answer(loser, at, qid).id == won.id
        loser.commit()
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Answer.id)).where(Answer.attempt_id == at, Answer.question_id == qid)) == 1

    # and the whole exam still closes and is marked when an answer already exists
    assert client.post(f"{API}/attempts/{at}/submit", headers=cand, json={}).status_code == 200
    _wait(lambda: _finished(client, cand, at), "the submission")
