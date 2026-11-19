"""Large-data test data for one run (S7), made with a few bulk SQL statements instead of thousands of API calls (password hashing would take an hour):
  - a question bank of BANK questions (default 5000),
  - CANDIDATES people with logins (default 5000; they all share the password of the run's first candidate),
  - a "Big Exam" of 40 questions that FINISHED people have already taken: finished attempts with answers and scores, so that results, analytics and exports
    can be measured on a thousand finished candidates.
Everything is named with the run id, so cleanup.py erases it with the rest. Run it INSIDE the exam server's container through standard input
(nothing is added to the image), or locally with the backend's Python:

  docker compose exec -T -e RUN=LT-20261120-2100 -e BANK=5000 -e CANDIDATES=5000 -e FINISHED=1000 api python - < bigdata.py
After it, add  "big_exam_id": "<printed id>"  to results/<run>/run.json (setup is printed on the last line)."""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.getcwd())
from sqlalchemy import text  # noqa: E402

from app.db import SessionLocal  # noqa: E402

RUN = os.environ.get("RUN", "")
BANK, PEOPLE, FINISHED = int(os.environ.get("BANK", "5000")), int(os.environ.get("CANDIDATES", "5000")), int(os.environ.get("FINISHED", "1000"))
if not re.fullmatch(r"LT-[0-9A-Za-z-]{3,40}", RUN):
    sys.exit("Set RUN to the run id, for example RUN=LT-20261120-2100")
FINISHED = min(FINISHED, PEOPLE)
t0 = time.time()
ID = "md5(random()::text || clock_timestamp()::text || {n})"

with SessionLocal() as db:
    dept = db.execute(text("select id, org_id from departments where name = :n"), {"n": f"{RUN} Department"}).one()
    pw = db.scalar(text("select password_hash from users where name like :l and password_hash is not null limit 1"), {"l": f"% {RUN} Candidate"})
    if not pw:
        sys.exit("Run setup_data.py first: no candidate of this run was found")
    p = {"dept": dept[0], "org": dept[1], "run": RUN, "pw": pw}

    db.execute(text(f"""insert into questions (id, org_id, department_id, type, title, body, difficulty, skills, marks, negative_marks, config, version, status, created_at, updated_at)
        select {ID.format(n="n")}, :org, :dept, 'mcq_single', :run || ' Bank ' || lpad(n::text, 5, '0'), '<p>Bank question ' || n || '</p>',
               (array['easy','medium','hard'])[1 + n % 3], '["load","bank"]'::json, 2, 0,
               cast(:opts as json),
               1, 'approved', now() - (n || ' seconds')::interval, now() - (n || ' seconds')::interval
        from generate_series(1, :bank) n"""), {**p, "bank": BANK, "opts": json.dumps({"options": [{"id": k, "text": k.upper(), "correct": k == "a"} for k in "abcd"]})})
    print(f"bank: {BANK} questions ({time.time() - t0:.0f} s)", flush=True)

    db.execute(text(f"""insert into users (id, org_id, email, username, name, phone, password_hash, mfa_enabled, status, failed_logins, created_at)
        select {ID.format(n="n")}, :org, 'bigcand' || n || '.' || lower(:run) || '@loadtest.invalid', 'big' || n || lower(replace(:run, '-', '')), :run || ' Big Candidate ' || lpad(n::text, 5, '0'),
               '', :pw, false, 'active', 0, now() - (n || ' seconds')::interval
        from generate_series(1, :people) n"""), {**p, "people": PEOPLE})
    db.execute(text("""insert into user_roles (user_id, role) select id, 'candidate' from users where name like :l and name like '% Big Candidate %'"""), {"l": f"{RUN} %"})
    print(f"people: {PEOPLE} ({time.time() - t0:.0f} s)", flush=True)

    test_id = db.scalar(text(f"""insert into tests (id, org_id, department_id, title, description, instructions, status, duration_min, access_enabled, cutoff, shuffle_questions,
                                                   shuffle_options, settings, calculated_at, created_at, updated_at)
        select {ID.format(n="0")}, :org, :dept, :run || ' Big Exam', 'Load test. Safe to delete.', '', 'published', 90, true, 40, true, true,
               cast(:settings as json), now(), now(), now() returning id"""), {**p, "settings": json.dumps({"proctoring": {"enabled": False}, "show_result_to_candidate": False})})
    section = db.scalar(text(f"insert into sections (id, test_id, title, \"order\", shuffle, lock_nav, allow_negative) select {ID.format(n='1')}, :t, 'All', 0, true, false, false returning id"), {"t": test_id})
    db.execute(text(f"""insert into section_items (id, section_id, kind, question_id, "order")
        select {ID.format(n='rn')}, :s, 'question', q.id, rn from (select id, row_number() over (order by title) rn from questions where title like :l and title like '% Bank %' limit 40) q"""),
               {"s": section, "l": f"{RUN} %"})
    db.execute(text(f"""insert into assignments (id, test_id, candidate_id, token_hash, status, invited_at, extra_time_min, reminders_sent, tag)
        select {ID.format(n='x.rn')}, :t, x.id, md5(random()::text || x.rn) || md5(x.id), case when x.rn <= :fin then 'evaluated' else 'invited' end, now() - interval '2 days', 0, 0, ''
        from (select id, row_number() over (order by name) rn from users where name like :l and name like '% Big Candidate %') x"""), {"t": test_id, "fin": FINISHED, "l": f"{RUN} %"})
    print(f"big exam {test_id}: assignments ({time.time() - t0:.0f} s)", flush=True)

    db.execute(text(f"""insert into attempts (id, assignment_id, test_id, candidate_id, status, started_at, deadline_at, submitted_at, submit_reason, seed, ip, user_agent, consent, system_check,
                                              section_state, seen, total_score, max_score, section_scores, below_cutoff, risk_score, risk_level, risk_breakdown, violations,
                                              plagiarism_level, plagiarism_max, feedback)
        select {ID.format(n='rn')}, a.id, a.test_id, a.candidate_id, 'evaluated', now() - interval '2 days', now() - interval '2 days' + interval '90 minutes',
               now() - interval '2 days' + ((20 + rn % 60) || ' minutes')::interval, 'submitted', rn, '10.0.0.1', 'load', '{{}}'::json, '{{}}'::json, '{{}}'::json, '{{}}'::json,
               (rn * 7 % 81)::numeric, 80, '{{}}'::json, (rn * 7 % 81) < 40, (rn % 40)::float, (array['low','low','medium','high'])[1 + rn % 4], '{{}}'::json, rn % 3, 'clear', 0, '{{}}'::json
        from (select id, test_id, candidate_id, row_number() over (order by id) rn from assignments where test_id = :t and status = 'evaluated') a"""), {"t": test_id})
    db.execute(text(f"""insert into attempt_questions (id, attempt_id, section_id, question_id, "order", option_order, marks, negative)
        select {ID.format(n='at.id || it.rn')}, at.id, :s, it.question_id, it.rn, '["a","b","c","d"]'::json, 2, 0
        from attempts at cross join (select question_id, "order" rn from section_items where section_id = :s) it where at.test_id = :t"""), {"t": test_id, "s": section})
    db.execute(text(f"""insert into answers (id, attempt_id, question_id, response, flagged, seq, saved_at, auto_score, ai_rationale, ai_detail, final_score, status, flags, feedback)
        select {ID.format(n='aq.id')}, aq.attempt_id, aq.question_id, ('{{"selected":["' || (array['a','b','c','d'])[1 + (length(aq.id) + aq."order") % 4] || '"]}}')::json,
               false, 1, now() - interval '2 days', case when (ascii(right(aq.id, 1)) + aq."order") % 3 = 0 then 2 else 0 end, '', '{{}}'::json,
               case when (ascii(right(aq.id, 1)) + aq."order") % 3 = 0 then 2 else 0 end, 'final', '[]'::json, ''
        from attempt_questions aq join attempts at on at.id = aq.attempt_id where at.test_id = :t"""), {"t": test_id})
    db.commit()
    counts = {t: db.scalar(text(f"select count(*) from {t} where " + w), {"t": test_id}) for t, w in
              (("attempts", "test_id = :t"), ("attempt_questions", "attempt_id in (select id from attempts where test_id = :t)"), ("answers", "attempt_id in (select id from attempts where test_id = :t)"))}
print(json.dumps({"big_exam_id": test_id, "bank": BANK, "people": PEOPLE, "finished": FINISHED, **counts, "seconds": round(time.time() - t0)}))
