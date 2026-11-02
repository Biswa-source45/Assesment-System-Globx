"""Seed the MVP: GLOBX organisation, six staff users, three candidates, a question bank covering all six
question types, a 6-section sample test and a practice test. Idempotent (skips if already seeded).

    python -m app.seed            # seed if empty
    python -m app.seed --reset    # wipe the database and seed again
"""
from __future__ import annotations

import json
import random
import sys
from datetime import timedelta

from sqlalchemy import select

from app.core.security import hash_password, new_password, new_token, sha256
from app.db import Base, SessionLocal, engine
from app.models import (Assignment, Organization, Question, QuestionGroup, Section, SectionItem, Test, TestCase,
                        User, UserRole, now, uid)

STAFF = [  # (email, name, roles) - passwords are generated at seed time and only written to data/seeded_accounts.txt
    ("superadmin@globx.co.in", "Super Admin", ["super_admin", "org_admin"]),
    ("orgadmin@globx.co.in", "Org Admin", ["org_admin"]),
    ("recruiter@globx.co.in", "Priya Recruiter", ["recruiter"]),
    ("creator@globx.co.in", "Tapas Test Creator", ["test_creator"]),
    ("evaluator@globx.co.in", "Lipsa Evaluator", ["evaluator"]),
]
CANDIDATES = [("rahul.mishra@example.com", "Rahul Mishra"), ("sneha.patnaik@example.com", "Sneha Patnaik"),
              ("amit.sahoo@example.com", "Amit Sahoo")]
W6 = [1, 1, 1, 2, 2, 3]
PURPOSE = ["Sample", "Basic", "Edge case", "Correctness", "Tricky cases", "Performance"]

LONG_RUBRIC = [
    {"id": "r1", "name": "Problem understanding", "max": 1, "descriptor": "0 missing - 0.5 partial - 1 clear restatement"},
    {"id": "r2", "name": "Key concepts", "max": 1, "descriptor": "Correct core mechanism named and explained"},
    {"id": "r3", "name": "Depth and examples", "max": 1, "descriptor": "Concrete example, data structures or numbers"},
    {"id": "r4", "name": "Correctness / failure handling", "max": 1, "descriptor": "Edge cases and failure modes covered"},
    {"id": "r5", "name": "Clarity and structure", "max": 1, "descriptor": "Organised, concise, readable"},
]

# ------------------------------------------------------------------ starter code
STARTER_PLATFORMS = {
    "python": "import sys\n\ndef main():\n    data = sys.stdin.read().split()\n    n = int(data[0])\n    # arrivals = data[1::2], departures = data[2::2]  (first n pairs)\n    # TODO: print the minimum number of platforms\n\nmain()\n",
    "java": "import java.io.*;\nimport java.util.*;\n\npublic class Main {\n    public static void main(String[] args) throws IOException {\n        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));\n        int n = Integer.parseInt(br.readLine().trim());\n        int[] arr = new int[n], dep = new int[n];\n        for (int i = 0; i < n; i++) {\n            StringTokenizer st = new StringTokenizer(br.readLine());\n            arr[i] = Integer.parseInt(st.nextToken());\n            dep[i] = Integer.parseInt(st.nextToken());\n        }\n        // TODO: print the minimum number of platforms\n    }\n}\n",
    "cpp": "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    ios::sync_with_stdio(false); cin.tie(nullptr);\n    int n; cin >> n;\n    vector<int> arr(n), dep(n);\n    for (int i = 0; i < n; i++) cin >> arr[i] >> dep[i];\n    // TODO: print the minimum number of platforms\n    return 0;\n}\n",
    "c": "#include <stdio.h>\n#include <stdlib.h>\n\nint main(void) {\n    int n; if (scanf(\"%d\", &n) != 1) return 0;\n    int *arr = malloc(n * sizeof(int)), *dep = malloc(n * sizeof(int));\n    for (int i = 0; i < n; i++) scanf(\"%d %d\", &arr[i], &dep[i]);\n    /* TODO: print the minimum number of platforms */\n    return 0;\n}\n",
    "javascript": "const data = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);\nconst n = data[0];\nconst arr = [], dep = [];\nfor (let i = 0; i < n; i++) { arr.push(data[1 + 2 * i]); dep.push(data[2 + 2 * i]); }\n// TODO: print the minimum number of platforms\n",
}
REF_PLATFORMS = ("import sys\n\ndef main():\n    d = sys.stdin.read().split()\n    n = int(d[0])\n    a = sorted(int(d[1 + 2 * i]) for i in range(n))\n"
                 "    b = sorted(int(d[2 + 2 * i]) for i in range(n))\n    i = j = cur = best = 0\n    while i < n:\n"
                 "        if a[i] <= b[j]:\n            cur += 1; i += 1; best = max(best, cur)\n        else:\n            cur -= 1; j += 1\n"
                 "    print(best)\n\nmain()\n")

STARTER_BRACKETS = {
    "python": "import sys\n\nlines = sys.stdin.read().split('\\n')\nt = int(lines[0])\nfor k in range(1, t + 1):\n    s = lines[k].strip()\n    # TODO: print YES if s is balanced, otherwise NO\n",
    "java": "import java.io.*;\n\npublic class Main {\n    public static void main(String[] args) throws IOException {\n        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));\n        int t = Integer.parseInt(br.readLine().trim());\n        StringBuilder out = new StringBuilder();\n        for (int k = 0; k < t; k++) {\n            String s = br.readLine();\n            if (s == null) s = \"\";\n            s = s.trim();\n            // TODO: append YES or NO\n        }\n        System.out.print(out);\n    }\n}\n",
    "cpp": "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    int t; cin >> t; string s; getline(cin, s);\n    while (t--) {\n        getline(cin, s);\n        // TODO: print YES or NO\n    }\n    return 0;\n}\n",
    "c": "#include <stdio.h>\n#include <string.h>\n\nstatic char s[200005];\n\nint main(void) {\n    int t; if (scanf(\"%d\", &t) != 1) return 0;\n    while (t--) {\n        if (scanf(\"%200000s\", s) != 1) s[0] = 0;\n        /* TODO: print YES or NO */\n    }\n    return 0;\n}\n",
    "javascript": "const lines = require('fs').readFileSync(0, 'utf8').split('\\n');\nconst t = parseInt(lines[0], 10);\nfor (let k = 1; k <= t; k++) {\n  const s = (lines[k] || '').trim();\n  // TODO: console.log YES or NO\n}\n",
}
REF_BRACKETS = ("import sys\n\nlines = sys.stdin.read().split('\\n')\nt = int(lines[0])\npair = {')': '(', ']': '[', '}': '{'}\nout = []\n"
                "for k in range(1, t + 1):\n    st = []\n    ok = True\n    for ch in lines[k].strip():\n        if ch in '([{':\n            st.append(ch)\n"
                "        elif ch in pair:\n            if not st or st.pop() != pair[ch]:\n                ok = False\n                break\n"
                "    out.append('YES' if ok and not st else 'NO')\nprint('\\n'.join(out))\n")

STARTER_SUM = {
    "python": "a, b = map(int, input().split())\n# TODO: print a + b\n",
    "java": "import java.util.*;\n\npublic class Main {\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);\n        long a = sc.nextLong(), b = sc.nextLong();\n        // TODO: print a + b\n    }\n}\n",
    "cpp": "#include <iostream>\nint main() {\n    long long a, b; std::cin >> a >> b;\n    // TODO: print a + b\n    return 0;\n}\n",
    "c": "#include <stdio.h>\nint main(void) {\n    long long a, b; scanf(\"%lld %lld\", &a, &b);\n    /* TODO: print a + b */\n    return 0;\n}\n",
    "javascript": "const [a, b] = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);\n// TODO: print a + b\n",
}


def _platforms_expected(pairs):
    a = sorted(p[0] for p in pairs)
    b = sorted(p[1] for p in pairs)
    i = j = cur = best = 0
    while i < len(a):
        if a[i] <= b[j]:
            cur += 1; i += 1; best = max(best, cur)
        else:
            cur -= 1; j += 1
    return str(best)


def _platform_cases():
    rnd = random.Random(7)
    sets = [
        [(900, 910), (940, 1200), (950, 1120)],
        [(900, 910), (940, 1200), (950, 1120), (1100, 1130), (1500, 1900), (1800, 2000)],
        [(1000, 1030)],
    ]
    def gen(n):
        out = []
        for _ in range(n):
            s = rnd.randint(0, 2200)
            out.append((s, min(2359, s + rnd.randint(0, 120))))
        return out
    sets += [gen(1000), [(t, t) for t in range(800, 900)] + gen(500), gen(100000)]
    cases = []
    for k, prs in enumerate(sets):
        inp = f"{len(prs)}\n" + "\n".join(f"{a} {b}" for a, b in prs) + "\n"
        cases.append((inp, _platforms_expected(prs)))
    return cases


def _brackets_cases():
    rnd = random.Random(11)
    def bal(s):
        st, pair = [], {")": "(", "]": "[", "}": "{"}
        for ch in s:
            if ch in "([{":
                st.append(ch)
            elif ch in pair:
                if not st or st.pop() != pair[ch]:
                    return "NO"
        return "YES" if not st else "NO"
    def rand_balanced(n):
        s, st = [], []
        for _ in range(n):
            if st and rnd.random() < 0.5:
                s.append({"(": ")", "[": "]", "{": "}"}[st.pop()])
            else:
                c = rnd.choice("([{"); st.append(c); s.append(c)
        while st:
            s.append({"(": ")", "[": "]", "{": "}"}[st.pop()])
        return "".join(s)
    sets = [["()[]{}", "([)]", "{[]}"], ["(", "()", "((()))", "}{"], ["", "[[[]]]"],
            [rand_balanced(rnd.randint(1, 50)) for _ in range(30)] + ["(]" * 3, "((("],
            ["(" * 500 + ")" * 499, "[" * 100 + "]" * 100, "{(})", "()" * 300],
            [rand_balanced(100000)]]
    out = []
    for s in sets:
        out.append((f"{len(s)}\n" + "\n".join(s) + "\n", "\n".join(bal(x) for x in s)))
    return out


SQL_SCHEMA = ("CREATE TABLE customers (id INTEGER PRIMARY KEY, name VARCHAR(50), city VARCHAR(50));\n"
              "CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, order_date DATE, amount DECIMAL(10,2));")
SQL_REF = ("SELECT c.name AS customer_name, SUM(o.amount) AS total FROM customers c JOIN orders o ON o.customer_id = c.id "
           "WHERE o.order_date >= '2025-01-01' AND o.order_date < '2026-01-01' GROUP BY c.name "
           "ORDER BY total DESC, customer_name LIMIT 3")


def _sql_datasets():
    rnd = random.Random(5)
    base = ("INSERT INTO customers VALUES (1,'Asha','Cuttack'),(2,'Bikash','Puri'),(3,'Chitra','Bhubaneswar'),"
            "(4,'Deepak','Rourkela');\n")
    ds = [base + "INSERT INTO orders VALUES (1,1,'2025-02-10',12000),(2,3,'2025-03-01',48200),(3,2,'2025-05-07',12400),"
                 "(4,1,'2025-06-11',19950),(5,4,'2024-12-30',99000);",
          base + "INSERT INTO orders VALUES (1,1,'2025-01-01',500),(2,2,'2025-12-31',700),(3,3,'2026-01-01',9999),(4,4,'2025-07-07',300);",
          base + "INSERT INTO orders VALUES (1,2,'2025-04-04',100);"]
    names = ["Asha", "Bikash", "Chitra", "Deepak", "Esha", "Farhan", "Gita", "Hari", "Ipsita", "Jagan"]
    for k in range(3):
        cust = ",".join(f"({i + 1},'{names[i]}','City{i}')" for i in range(10))
        rows = []
        for i in range(60 + 40 * k):
            y = rnd.choice([2024, 2025, 2025, 2026])
            amt = rnd.choice([1000, 2500, 2500, 400, 7000, 1200]) if k == 1 else rnd.randint(1, 5000)
            rows.append(f"({i + 1},{rnd.randint(1, 10)},'{y}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}',{amt})")
        ds.append(f"INSERT INTO customers VALUES {cust};\nINSERT INTO orders VALUES {','.join(rows)};")
    return ds


def mcq(org, title, body, opts, correct, diff, skills, marks=1.0, neg=0.0, group=None, multi=False):
    q = Question(id=uid(), org_id=org, type="mcq_multi" if multi else "mcq_single", title=title, body=body,
                 difficulty=diff, skills=skills, marks=marks, negative_marks=neg, group_id=group,
                 config={"options": [{"id": chr(97 + i), "text": t, "correct": chr(97 + i) in correct} for i, t in enumerate(opts)],
                         "partial": True})
    return q


def seed(reset: bool = False) -> dict:
    from app import models  # noqa: F401
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.scalar(select(Organization).where(Organization.slug == "globx")):
            return {"seeded": False, "message": "Already seeded (use --reset to start over)"}
        org = Organization(id=uid(), name="GLOBX System & Network Pvt Ltd", slug="globx", plan="enterprise",
                           credits=10000, data_region="IN")
        db.add(org)
        db.flush()
        staff = [(e, n, new_password(12), r) for e, n, r in STAFF]
        cand_pw = new_password(12)
        users = {}
        for email, name, pw, roles in staff:
            u = User(id=uid(), org_id=org.id, email=email, name=name, password_hash=hash_password(pw))
            u.roles = [UserRole(role=r) for r in roles]
            db.add(u)
            users[email] = u
        creator = users["creator@globx.co.in"].id
        O = org.id
        qs = []
        # ---------------- MCQ single (pool of 8)
        qs += [
            mcq(O, "Static method hiding", "<p>What does this Java code print?</p><pre><code>class A { static String who() { return \"A\"; } }\nclass B extends A { static String who() { return \"B\"; } }\nA obj = new B();\nSystem.out.println(obj.who());</code></pre>",
                ["B", "A", "Compilation error", "Runtime exception"], "b", "medium", ["java", "oop"]),
            mcq(O, "Python default argument", "<p>What is printed?</p><pre><code>def f(x, acc=[]):\n    acc.append(x)\n    return acc\nf(1)\nprint(f(2))</code></pre>",
                ["[2]", "[1, 2]", "[1]", "Error"], "b", "medium", ["python"]),
            mcq(O, "Binary search complexity", "<p>Worst-case time complexity of binary search on a sorted array of n elements?</p>",
                ["O(n)", "O(log n)", "O(n log n)", "O(1)"], "b", "easy", ["algorithms"]),
            mcq(O, "HTTP status for created", "<p>Which status code should a REST API return after successfully creating a resource?</p>",
                ["200 OK", "201 Created", "204 No Content", "302 Found"], "b", "easy", ["web", "rest"]),
            mcq(O, "LEFT JOIN result", "<p>Table A has 5 rows, table B has 3 rows and no keys match. How many rows does <code>A LEFT JOIN B</code> return?</p>",
                ["0", "3", "5", "15"], "c", "medium", ["sql"]),
            mcq(O, "JavaScript equality", "<p>What is the value of <code>0 == '0' &amp;&amp; 0 === '0'</code> in JavaScript?</p>",
                ["true", "false", "undefined", "TypeError"], "b", "easy", ["javascript"]),
            mcq(O, "HashMap worst case", "<p>Average and worst case lookup in Java 8+ HashMap when many keys collide in one bucket?</p>",
                ["O(1) / O(n)", "O(1) / O(log n)", "O(log n) / O(n)", "O(1) / O(1)"], "b", "hard", ["java", "data-structures"]),
            mcq(O, "Deadlock condition", "<p>Which of these is NOT one of the four Coffman conditions for deadlock?</p>",
                ["Mutual exclusion", "Hold and wait", "Preemption", "Circular wait"], "c", "hard", ["os"]),
        ]
        # ---------------- MCQ multiple (fixed)
        qs += [
            mcq(O, "Idempotent HTTP methods", "<p>Which HTTP methods are idempotent by definition? (select all that apply)</p>",
                ["GET", "POST", "PUT", "DELETE"], "acd", "medium", ["web", "rest"], 1.0, 0.25, multi=True),
            mcq(O, "O(1) average lookup", "<p>Which structures give O(1) average-time membership lookup?</p>",
                ["Hash set", "Balanced BST", "Hash map", "Sorted array"], "ac", "easy", ["data-structures"], 1.0, 0.25, multi=True),
        ]
        # ---------------- Linked MCQ group (2 marks, -0.5)
        g = QuestionGroup(id=uid(), org_id=O, title="Case study: shipment database performance", skills=["sql", "performance"],
                          stimulus="<p>A logistics company stores shipments in table <b>shipment(id, origin, dest, weight_kg, status, created_at)</b>. "
                                   "About 2 million rows are inserted every day. Analysts report that this query takes 40 seconds:</p>"
                                   "<pre><code>SELECT dest, COUNT(*) FROM shipment\nWHERE status = 'DELIVERED' AND created_at &gt;= now() - interval '7 days'\nGROUP BY dest;</code></pre>"
                                   "<p>The application tier is a Spring Boot service with a connection pool of 20 and a p95 latency target of 300 ms.</p>")
        db.add(g)
        db.flush()
        qs += [
            mcq(O, "Most selective index", "<p>Which single index helps this query most?</p>",
                ["(dest)", "(status, created_at, dest)", "(weight_kg)", "(id)"], "b", "medium", ["sql"], 2.0, 0.5, g.id),
            mcq(O, "Two changes that reduce query time", "<p>Which TWO changes will most reduce the query time?</p>",
                ["Composite index on (status, created_at, dest)", "Increase the connection pool to 100",
                 "Monthly range partitioning on created_at", "Change weight_kg to NUMERIC(10,2)"], "ac", "hard", ["sql"], 2.0, 0.5, g.id, multi=True),
            mcq(O, "Effect of a bigger pool", "<p>What is the most likely effect of raising the pool from 20 to 100 connections for this query?</p>",
                ["Query becomes 5x faster", "No real improvement; DB contention may rise", "Rows are cached in the pool", "Index is used automatically"],
                "b", "medium", ["performance"], 2.0, 0.5, g.id),
        ]
        # ---------------- Short answer (2 marks)
        qs += [
            Question(id=uid(), org_id=O, type="short", title="What is an idempotency key?", difficulty="easy", skills=["api"],
                     body="<p>In two or three sentences, explain what an <b>idempotency key</b> is in an API and why it is used.</p>",
                     marks=2, config={"model_answer": "A unique client-generated key sent with a mutating request so the server can detect retries and return the stored result instead of executing the operation twice, preventing duplicate side effects such as double payments.",
                                      "keywords": ["unique|uuid", "retry|retries", "duplicate|twice|double", "same result|stored response|cached response"],
                                      "max_words": 150}),
            Question(id=uid(), org_id=O, type="short", title="Database normalisation", difficulty="easy", skills=["sql"],
                     body="<p>What is database normalisation and what problem does it solve?</p>", marks=2,
                     config={"model_answer": "Organising tables to remove redundancy by splitting data into related tables (1NF, 2NF, 3NF) so each fact is stored once, avoiding update, insert and delete anomalies.",
                             "keywords": ["redundancy|duplication", "anomal", "normal form|1nf|2nf|3nf", "related tables|foreign key"],
                             "max_words": 150}),
        ]
        # ---------------- Long answer (5 marks)
        qs += [
            Question(id=uid(), org_id=O, type="long", title="Design idempotent payment APIs", difficulty="hard", skills=["system-design", "api"],
                     body="<p>Explain how you would design <b>idempotent payment APIs</b> in a microservice architecture. Cover retries, idempotency keys, storage and failure scenarios.</p>",
                     marks=5, config={"model_answer": "Client sends Idempotency-Key header; server stores key with request hash and status in a table with a unique constraint; concurrent duplicates handled by row locks or insert-if-absent; responses replayed for repeated keys; keys expire after a retention period; mismatched payload returns 422; gateway timeouts leave state IN_PROGRESS and a reconciler polls the provider; exactly-once effect via outbox pattern.",
                                      "rubric": LONG_RUBRIC, "min_words": 100, "max_words": 800, "allow_file": True, "show_rubric": True}),
            Question(id=uid(), org_id=O, type="long", title="Scaling a read-heavy web application", difficulty="medium", skills=["system-design"],
                     body="<p>A web application serves 50,000 requests per minute, 95% of them reads. Describe how you would scale it.</p>",
                     marks=5, config={"model_answer": "Caching layers (CDN, Redis) with TTL and invalidation, read replicas, connection pooling, horizontal stateless app servers behind a load balancer, pagination and indexing, async jobs, monitoring of cache hit ratio and p95 latency.",
                                      "rubric": LONG_RUBRIC, "min_words": 100, "max_words": 800, "allow_file": True}),
        ]
        # ---------------- Programming (10 marks each)
        def coding(title, body, diff, skills, starter, ref, cases, time_ms=2000):
            q = Question(id=uid(), org_id=O, type="coding", title=title, body=body, difficulty=diff, skills=skills, marks=10,
                         config={"time_limit_ms": time_ms, "memory_mb": 256, "comparator": "trim",
                                 "languages": ["python", "java", "cpp", "c", "javascript"], "starter": starter,
                                 "reference": {"language": "python", "source": ref}, "editorial": ""})
            for i, (inp, exp) in enumerate(cases):
                q.cases.append(TestCase(id=uid(), ordinal=i + 1, visibility="open" if i < 3 else "hidden", input=inp,
                                        expected=exp, weight=W6[i], purpose=PURPOSE[i]))
            return q
        qs.append(coding("Minimum Platforms",
                         "<p>Given the arrival and departure times of <b>N</b> trains (24-hour HHMM integers), find the minimum number of platforms "
                         "needed so that no train waits. A train that arrives at the same minute another departs needs a separate platform.</p>"
                         "<p><b>Input:</b> N, then N lines <code>arr dep</code>.<br><b>Output:</b> one integer.<br><b>Constraints:</b> 1 &le; N &le; 10<sup>5</sup></p>"
                         "<p><b>Sample input</b></p><pre>3\n900 910\n940 1200\n950 1120</pre><p><b>Sample output</b></p><pre>2</pre>",
                         "medium", ["greedy", "sorting"], STARTER_PLATFORMS, REF_PLATFORMS, _platform_cases()))
        qs.append(coding("Balanced Brackets",
                         "<p>For each of T strings made of <code>()[]{}</code>, print <b>YES</b> if the brackets are balanced, otherwise <b>NO</b>.</p>"
                         "<p><b>Input:</b> T, then T lines.<br><b>Output:</b> T lines.<br><b>Constraints:</b> total length &le; 2&times;10<sup>5</sup></p>"
                         "<p><b>Sample input</b></p><pre>3\n()[]{}\n([)]\n{[]}</pre><p><b>Sample output</b></p><pre>YES\nNO\nYES</pre>",
                         "easy", ["stack", "strings"], STARTER_BRACKETS, REF_BRACKETS, _brackets_cases()))
        sum_cases = [("2 3\n", "5"), ("10 20\n", "30"), ("0 0\n", "0"), ("-5 5\n", "0"), ("123456789 987654321\n", "1111111110"),
                     ("1000000000000 1000000000000\n", "2000000000000")]
        q_sum = coding("Sum of Two Numbers", "<p>Read two integers <code>a b</code> and print their sum.</p><p><b>Sample input</b></p><pre>2 3</pre><p><b>Sample output</b></p><pre>5</pre>",
                       "easy", ["basics"], STARTER_SUM, "a, b = map(int, input().split())\nprint(a + b)\n", sum_cases)
        qs.append(q_sum)
        # ---------------- SQL (10 marks)
        q_sql = Question(id=uid(), org_id=O, type="sql", title="Top customers by revenue (2025)", difficulty="medium", skills=["sql"],
                         body="<p>Return the <b>top 3 customers by total order amount in calendar year 2025</b>. Columns: <code>customer_name</code>, "
                              "<code>total</code>. Order by total descending, then customer_name ascending.</p>",
                         marks=10, config={"schema": SQL_SCHEMA, "seed": "", "engines": ["sqlite", "postgresql", "mysql"],
                                           "ordered": True, "reference_sql": SQL_REF})
        for i, ds in enumerate(_sql_datasets()):
            q_sql.cases.append(TestCase(id=uid(), ordinal=i + 1, visibility="open" if i < 3 else "hidden", input=ds,
                                        expected="", weight=W6[i], purpose=PURPOSE[i]))
        qs.append(q_sql)
        for q in qs:
            q.created_by = creator
            db.add(q)
        db.flush()
        # validate coding + SQL with the sandbox (fills SQL expected results)
        from app.sandbox.judge import judge_code, judge_sql, sql_expected_for
        for q in qs:
            if q.type == "sql":
                for c in q.cases:
                    c.expected = json.dumps(sql_expected_for(q.config, c.input))
                cases = [{"ordinal": c.ordinal, "visibility": c.visibility, "input": c.input, "expected": c.expected,
                          "weight": float(c.weight)} for c in q.cases]
                r = judge_sql(q.config, cases, "sqlite", q.config["reference_sql"], "validate")
            elif q.type == "coding":
                cases = [{"ordinal": c.ordinal, "visibility": c.visibility, "input": c.input, "expected": c.expected,
                          "weight": float(c.weight)} for c in q.cases]
                r = judge_code(q.config, cases, "python", q.config["reference"]["source"], "validate")
            else:
                continue
            ok = r.get("passed") == r.get("total") == 6
            q.config = {**q.config, "validated": ok}
            print(f"  validated {q.title}: {'OK' if ok else 'FAILED ' + str([c['verdict'] for c in r.get('cases', [])])}")
        # ---------------- sample test
        by = {q.title: q for q in qs}
        t = Test(id=uid(), org_id=O, title="GLOBX Full-Stack Screening (Sample)", status="published", duration_min=90,
                 description="Sample 6-section assessment: MCQ, Linked MCQ, Short, Long, Programming and SQL.",
                 instructions="<p>Read each question carefully. MCQs carry 1 mark; Linked MCQs carry 2 marks with -0.5 for a wrong answer. "
                              "Programming questions carry 10 marks: 3 open test cases (1 mark each) and 3 hidden test cases (2, 2 and 3 marks). "
                              "The test is proctored throughout: keep your face visible, stay in fullscreen and do not switch tabs.</p>",
                 starts_at=now() - timedelta(hours=1), ends_at=now() + timedelta(days=30), cutoff=25, created_by=creator,
                 settings={"proctoring": {"enabled": True, "webcam": True, "snapshot_seconds": 15, "fullscreen": True,
                                          "tab_switch_limit": 3, "limit_action": "submit", "block_paste": True,
                                          "screen_capture": False, "audio": True, "block_multi_display": True},
                           "show_result_to_candidate": True})
        sA = Section(id=uid(), title="A - MCQ", order=0, timer_min=None)
        sA.items.append(SectionItem(id=uid(), kind="pool", order=0, pool={"filter": {"types": ["mcq_single"]}, "draw": 5,
                                                                          "mix": {"easy": 2, "medium": 2, "hard": 1}, "marks_each": 1}))
        sA.items.append(SectionItem(id=uid(), kind="question", question_id=by["Idempotent HTTP methods"].id, order=1))
        sA.items.append(SectionItem(id=uid(), kind="question", question_id=by["O(1) average lookup"].id, order=2))
        sB = Section(id=uid(), title="B - Linked MCQ", order=1)
        sB.items.append(SectionItem(id=uid(), kind="group", group_id=g.id, order=0))
        sC = Section(id=uid(), title="C - Short answer", order=2)
        for i, k in enumerate(["What is an idempotency key?", "Database normalisation"]):
            sC.items.append(SectionItem(id=uid(), kind="question", question_id=by[k].id, order=i))
        sD = Section(id=uid(), title="D - Long answer", order=3)
        sD.items.append(SectionItem(id=uid(), kind="question", question_id=by["Design idempotent payment APIs"].id, order=0))
        sE = Section(id=uid(), title="E - Programming", order=4, shuffle=False)
        for i, k in enumerate(["Minimum Platforms", "Balanced Brackets"]):
            sE.items.append(SectionItem(id=uid(), kind="question", question_id=by[k].id, order=i))
        sF = Section(id=uid(), title="F - SQL", order=5)
        sF.items.append(SectionItem(id=uid(), kind="question", question_id=q_sql.id, order=0))
        t.sections = [sA, sB, sC, sD, sE, sF]
        db.add(t)
        # practice test (no proctoring)
        p = Test(id=uid(), org_id=O, title="Practice Test", status="published", duration_min=20, cutoff=0, created_by=creator,
                 description="Get familiar with the test environment. Not scored for hiring.",
                 instructions="<p>This practice test is not proctored and does not count.</p>",
                 settings={"proctoring": {"enabled": False, "webcam": False, "fullscreen": False, "tab_switch_limit": 0,
                                          "audio": False, "block_paste": False, "block_multi_display": False},
                           "show_result_to_candidate": True, "practice": True})
        ps = Section(id=uid(), title="Practice", order=0)
        ps.items.append(SectionItem(id=uid(), kind="question", question_id=by["Binary search complexity"].id, order=0))
        ps.items.append(SectionItem(id=uid(), kind="question", question_id=q_sum.id, order=1))
        ps.items.append(SectionItem(id=uid(), kind="question", question_id=by["What is an idempotency key?"].id, order=2))
        p.sections = [ps]
        db.add(p)
        db.flush()
        links = []
        for email, name in CANDIDATES:
            u = User(id=uid(), org_id=O, email=email, name=name, username=name.split()[0].lower(),
                     password_hash=hash_password(cand_pw))
            u.roles = [UserRole(role="candidate")]
            db.add(u)
            db.flush()
            for test in (t, p):
                tok = new_token(32)
                db.add(Assignment(id=uid(), test_id=test.id, candidate_id=u.id, token_hash=sha256(tok),
                                  expires_at=now() + timedelta(days=30), sent_at=now(), tag="seed"))
                links.append((email, test.title, tok))
        db.commit()
        return {"seeded": True, "links": links, "staff": [(e, p, r) for e, _, p, r in staff],
                "candidate_password": cand_pw}
    finally:
        db.close()


def main():
    from app.core.config import get_settings, BACKEND_DIR
    reset = "--reset" in sys.argv
    res = seed(reset=reset)
    if not res.get("seeded"):
        print(res["message"])
        return
    base = get_settings().public_base_url.rstrip("/")
    lines = ["GLOBX Assess - seeded accounts", "", "STAFF (password login at /#/login):"]
    for e, p, r in res["staff"]:
        lines.append(f"  {e:<28} {p:<14} {', '.join(r)}")
    lines += ["", f"CANDIDATES (username rahul / sneha / amit, password {res['candidate_password']}, or the old email-OTP invite link):"]
    for e, title, tok in res["links"]:
        lines.append(f"  {e:<28} {title:<38} {base}/#/invite/{tok}")
    text = "\n".join(lines)
    print(text)
    out = BACKEND_DIR / "data" / "seeded_accounts.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
