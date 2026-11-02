from app.domain.scoring import (compare_output, cross_verification_flags, keyword_coverage, score_cases, score_mcq,
                                score_rubric, score_short)

OPTS = ["a", "b", "c", "d"]


def test_mcq_single():
    assert score_mcq(["b"], ["b"], OPTS, 1, 0, False) == 1
    assert score_mcq(["a"], ["b"], OPTS, 1, 0.25, False) == -0.25
    assert score_mcq([], ["b"], OPTS, 1, 0.25, False) == 0


def test_linked_mcq_worked_example_from_srs():
    # 2 marks, -0.5 negative, correct A and C
    f = lambda sel: score_mcq(sel, ["a", "c"], OPTS, 2, 0.5, True, True)
    assert f(["a"]) == 1.0
    assert f(["a", "c"]) == 2.0
    assert f(["a", "b"]) == 0.75
    assert f(["b"]) == -0.25
    assert f(["b", "d"]) == -0.5
    assert f(["a", "c", "d"]) == -0.5  # over-selection


def test_hackerearth_partial_example():
    f = lambda sel: score_mcq(sel, ["a", "c"], OPTS, 4, 2, True, True)
    assert [f(["a"]), f(["b"]), f(["a", "c"]), f(["a", "b"]), f(["b", "d"]), f(["a", "c", "d"])] == [2, -1, 4, 1, -2, -2]


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
