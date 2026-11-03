"""Can this process reach the judge and get an honest answer from it? `python -m app.sandbox.probe` (uses JUDGE_URL). Prints AC and exits 0 when it can."""
import sys

from app.sandbox import judge

case = [{"id": "1", "ordinal": 1, "visibility": "hidden", "input": "", "expected": "hi", "weight": 1}]
res = judge.judge_code({"time_limit_ms": 3000, "memory_mb": 128}, case, "python", "print('hi')\n", "validate")
verdict = res["cases"][0]["verdict"] if res.get("cases") else res.get("error", res.get("status"))
print(verdict)
sys.exit(0 if verdict == "AC" else 1)
