from app.domain import plagiarism as P
from app.domain.risk import compute


def test_risk_levels_and_rules():
    r = compute([{"type": "tab_blur", "duration_ms": 500}])
    assert r["score"] == 0 and r["violations"] == 0
    r = compute([{"type": "tab_blur", "duration_ms": 40000}, {"type": "fs_exit"}])
    assert r["score"] == 22 and r["level"] == "medium" and r["violations"] == 2
    r = compute([{"type": "multi_face"}] * 5)
    assert r["score"] == 75 and r["level"] == "critical"
    r = compute([{"type": "vm_detected"}, {"type": "vm_detected"}])
    assert r["score"] == 20


def test_code_similarity_detects_renamed_copy():
    a = "\n".join(["def solve(nums):", "    total = 0", "    for n in nums:", "        if n % 2 == 0:", "            total += n * n",
                   "        else:", "            total -= n", "    return total", "print(solve([1,2,3,4,5,6,7,8]))"] * 2)
    b = a.replace("total", "acc").replace("nums", "values").replace("solve", "f")
    sim, run, _ = P.code_similarity(a, b, "python")
    assert sim >= 0.85
    c = "import sys\nx = sys.stdin.read().split()\nprint(sorted(map(int, x))[::-1][:3])\n" * 3
    assert P.code_similarity(a, c, "python")[0] < 0.6


def test_text_similarity():
    t = "an idempotency key is a unique value sent by the client so the server can recognise retries and return the stored response instead of charging twice"
    assert P.text_similarity(t, t) == 1.0
    assert P.text_similarity(t, "normalisation splits tables to remove redundancy and avoid update anomalies in relational databases today") < 0.2
