from app.domain.scoring import (compare_output, cross_verification_flags, keyword_coverage, score_cases, score_mcq,
                                score_rubric, score_short)

OPTS = ["a", "b", "c", "d"]


def test_mcq_single():
    assert score_mcq(["b"], ["b"], OPTS, 1, 0, False) == 1
    assert score_mcq(["a"], ["b"], OPTS, 1, 0.25, False) == -0.25
    assert score_mcq([], ["b"], OPTS, 1, 0.25, False) == 0


def test_multiple_answer_is_strict():
    # 5 options (a-e), 3 right (a, b, c), 3 marks. Right ticks share the marks; each wrong tick takes 0.25; never below 0.
    opts = ["a", "b", "c", "d", "e"]
    f = lambda sel, marks=3: score_mcq(sel, ["a", "b", "c"], opts, marks, 0, True, True)
    assert f(["a", "b", "c"]) == 3.0
    assert f(["a", "b", "c", "d"]) == 2.75      # all right plus one wrong: only 0.25 off (used to be negative)
    assert f(["a", "b"]) == 2.0                  # two thirds
    assert f(["a", "d"]) == 0.75                 # 1 right (1.0) - 0.25
    assert f(["d"]) == 0.0                       # a wrong tick alone never goes below zero
    assert f(["d", "e"]) == 0.0
    assert f([]) == 0.0
    assert f(["a", "b", "c", "d", "e"]) == 0.0   # ticking everything does not win
    assert f(["a", "x"]) == 1.0                  # an option that does not exist is ignored
    assert f(["a"], marks=0.5) == 0.17           # small marks: the share is rounded to 2 places
    assert score_mcq(["a", "b"], ["a", "b"], ["a", "b"], 2, 0, True, True) == 2.0  # every option is right: ticking all is right
    # without partial marks only the exact set earns anything
    g = lambda sel: score_mcq(sel, ["a", "b", "c"], opts, 3, 0, True, False)
    assert [g(["a", "b", "c"]), g(["a", "b"]), g(["a", "b", "c", "d"])] == [3.0, 0.0, 0.0]


def test_the_question_s_own_negative_marks_do_not_change_multiple_answer():
    f = lambda neg: score_mcq(["a", "d"], ["a", "b"], OPTS, 2, neg, True, True)
    assert f(0) == f(2) == 0.75


def test_short_answer():
    cov = keyword_coverage("A unique key lets retries avoid duplicate charges", ["unique|uuid", "retry|retries", "duplicate", "ledger"])
    assert cov == 0.75
    assert score_short(2, cov, None) == 1.5
    assert score_short(2, 1.0, 0.5) == 1.5  # 2*(0.4+0.3)=1.4 -> 1.5 (quarter rounding)


def test_rubric_and_cases():
    rub = [{"id": "r1", "max": 1}, {"id": "r2", "max": 1}]
    assert score_rubric(rub, [{"id": "r1", "score": 0.75}, {"id": "r2", "score": 3}]) == 1.75
    res = [{"weight": 1, "passed": True, "visibility": "open"}] * 3 + [{"weight": 2, "passed": False, "visibility": "hidden"}] * 3
    assert score_cases(res) == 3
    assert cross_verification_flags(res) == ["possible_hard_coding"]


def test_comparators():
    assert compare_output("5 \n\n", "5")
    assert not compare_output("5", "6")
    assert compare_output("1.0000001", "1.0", "float")
    assert compare_output("1  2\n3", "1 2 3", "token")
