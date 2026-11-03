"""Attack drill for the isolated judge. Run it INSIDE the judge container, never on a developer machine:

    docker compose run --rm judge python -m app.sandbox.hostile

Every program below does what a hostile candidate might try. Each must fail or be stopped, and afterwards the judge must be exactly as healthy
as before: the service alive, no run folder or process left behind. Exit code 0 only when every attack failed."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Callable, Dict, List, Optional, Set

import psutil

from app.core.config import get_settings
from app.sandbox.judge import local_judge_code, local_judge_sql

SECRET_FILE = "/tmp/oap-root-secret"
SECRET = "TOP-SECRET-DATA"
OK = "AC"  # the program prints BLOCKED when the attack failed, so the expected output "BLOCKED" matching means the attack failed
CASE = [{"id": "1", "ordinal": 1, "visibility": "hidden", "input": "", "expected": "BLOCKED", "weight": 1}]
STOPPED = {"TLE", "MLE", "OLE", "RE", "CE", "IE"}  # any of these is the judge stopping a resource attack
results: List[Dict] = []


def py(body: str) -> str:
    """A Python program that prints BLOCKED unless the attack in `body` worked (it then sets r = 'LEAK'); any error means it was blocked."""
    inner = "\n".join("    " + line for line in body.strip().splitlines())
    return f"import os, socket, ctypes, glob, time\nr = 'BLOCKED'\ntry:\n{inner}\nexcept BaseException:\n    pass\nprint(r)\n"


def attack(name: str, source: str, language: str = "python", expect: Optional[Set[str]] = None, time_ms: int = 3000, mem: int = 128,
           check: Optional[Callable[[Dict], Optional[str]]] = None) -> None:
    """expect None: the attack must fail (output BLOCKED). Otherwise: the verdict must be one of `expect`. check() returns a problem text or None."""
    t = time.time()
    res = local_judge_code({"time_limit_ms": time_ms, "memory_mb": mem}, CASE, language, source, "validate")
    verdict = res["cases"][0]["verdict"] if res.get("cases") else res.get("status")
    problem = None
    if expect is None and verdict != OK:
        problem = f"verdict {verdict}, the program did not report BLOCKED: {res['cases'][0].get('stdout', '')[:60] if res.get('cases') else res.get('error')}"
    elif expect is not None and verdict not in expect:
        problem = f"verdict {verdict}, expected one of {sorted(expect)}"
    if problem is None and check:
        problem = check(res)
    results.append({"name": name, "ok": problem is None, "detail": problem or verdict, "seconds": round(time.time() - t, 1)})


def sql_attack(name: str, query: str, expect_not_ok: bool = True, check: Optional[Callable[[], Optional[str]]] = None) -> None:
    t = time.time()
    cfg = {"schema": "CREATE TABLE t (x INTEGER);", "seed": "", "engines": ["sqlite"], "ordered": True}
    case = [{"id": "1", "ordinal": 1, "visibility": "hidden", "input": "INSERT INTO t VALUES (1);", "expected": json.dumps({"columns": ["x"], "rows": [[1]]}), "weight": 1}]
    rss = psutil.Process().memory_info().rss
    res = local_judge_sql(cfg, case, "sqlite", query, "submit")
    verdict = res["cases"][0]["verdict"] if res.get("cases") else res.get("status")
    problem = f"the query was accepted (verdict {verdict})" if expect_not_ok and verdict == OK else None
    grown = (psutil.Process().memory_info().rss - rss) / 1048576
    if problem is None and grown > 1000:
        problem = f"the judge grew by {grown:.0f} MB"
    if problem is None and check:
        problem = check()
    results.append({"name": name, "ok": problem is None, "detail": problem or f"{verdict}, memory +{grown:.0f} MB", "seconds": round(time.time() - t, 1)})


def refuse_outside_the_container() -> None:
    s = get_settings()
    problems = []
    if os.name == "nt" or os.getuid() != 0:
        problems.append("it must run as the judge service (root inside the container)")
    if not s.sandbox_uid_base:
        problems.append("SANDBOX_UID_BASE is not set")
    if problems:
        sys.exit("Run this drill inside the judge container: " + "; ".join(problems))


def container_is_locked() -> None:
    """The drill is only meaningful if the container really is locked down."""
    import socket
    try:
        open("/etc/oap-write-test", "w").close()
        results.append({"name": "container: root filesystem is read-only", "ok": False, "detail": "a file could be created in /etc", "seconds": 0})
    except OSError:
        results.append({"name": "container: root filesystem is read-only", "ok": True, "detail": "cannot write", "seconds": 0})
    try:
        socket.create_connection(("1.1.1.1", 80), timeout=2).close()
        results.append({"name": "container: no network", "ok": False, "detail": "the internet is reachable", "seconds": 0})
    except OSError:
        results.append({"name": "container: no network", "ok": True, "detail": "no route", "seconds": 0})


def main() -> int:
    refuse_outside_the_container()
    s = get_settings()
    base, work = s.sandbox_uid_base, s.sandbox_dir
    pid = os.getpid()
    with open(SECRET_FILE, "w") as f:
        f.write(SECRET)
    os.chmod(SECRET_FILE, 0o600)
    processes_before = len([p for p in psutil.process_iter(['status']) if p.info['status'] != psutil.STATUS_ZOMBIE])
    container_is_locked()

    # --- reading and reaching what a run must not
    attack("read the judge service's environment", py(f"open('/proc/{pid}/environ').read(); r = 'LEAK'"))
    attack("read a root-only file", py(f"open('{SECRET_FILE}').read(); r = 'LEAK'"))
    attack("list the folder that holds every run", py(f"os.listdir('{work}'); r = 'LEAK'"))
    attack("reach the internet", py("socket.create_connection(('1.1.1.1', 80), timeout=2); r = 'LEAK'"))
    attack("reach the judge's own socket", py("c = socket.socket(socket.AF_UNIX); c.connect('/run/judge/judge.sock'); r = 'LEAK'"))
    attack("write outside its folder", py("for p in ('/etc/oap-pwned', '/usr/oap-pwned', '/oap-pwned', '/run/oap-pwned', '/srv/oap-pwned'):\n    open(p, 'w').write('x')\n    r = 'LEAK'"))
    attack("become root", py("os.setuid(0); r = 'LEAK'"))
    attack("run as root", py("r = 'LEAK' if os.getuid() == 0 or os.geteuid() == 0 else 'BLOCKED'"))
    attack("kill the judge service", py(f"os.kill({pid}, 9); r = 'LEAK'"))
    attack("mount a disk", py("libc = ctypes.CDLL(None, use_errno=True)\nif libc.mount(b'none', b'/mnt', b'tmpfs', 0, None) == 0:\n    r = 'LEAK'"))
    attack("read a root-only file from C", "#include <stdio.h>\nint main(void){ puts(fopen(\"" + SECRET_FILE + "\", \"r\") ? \"LEAK\" : \"BLOCKED\"); return 0; }\n", "c")
    attack("read a root-only file from Java", "public class Main { public static void main(String[] a) { try { new java.io.FileReader(\"" + SECRET_FILE + "\").read(); System.out.println(\"LEAK\"); } catch (Exception e) { System.out.println(\"BLOCKED\"); } } }\n", "java", time_ms=5000, mem=256)
    attack("read a root-only file from JavaScript", "try { require('fs').readFileSync('" + SECRET_FILE + "'); console.log('LEAK'); } catch (e) { console.log('BLOCKED'); }\n", "javascript", time_ms=3000, mem=256)

    def leaked_text(res: Dict) -> Optional[str]:
        return "the secret appeared in the compiler message" if SECRET in json.dumps(res) else None
    attack("include a root-only file at compile time", f'#include "{SECRET_FILE}"\nint main(void){{ return 0; }}\n', "c", expect={"CE"}, check=leaked_text)
    attack("include another process's environment at compile time", f'#include "/proc/{pid}/environ"\nint main(void){{ return 0; }}\n', "c", expect={"CE"}, check=leaked_text)

    # --- one candidate spying on another running at the same time
    spy_result: Dict = {}

    def victim():
        local_judge_code({"time_limit_ms": 6000}, CASE, "python", "open('secret.txt', 'w').write('NEIGHBOUR-SECRET')\nimport time; time.sleep(3)\nprint('BLOCKED')\n", "validate")

    thread = threading.Thread(target=victim)
    thread.start()
    time.sleep(1.2)
    attack("read another run's files while it is running", py(f"import glob\nfor p in glob.glob('{work}/*/secret.txt'):\n    if 'NEIGHBOUR' in open(p).read():\n        r = 'LEAK'"))
    thread.join()

    # --- resource attacks: the judge must stop them
    attack("endless loop", "while True:\n    pass\n", expect={"TLE"})
    attack("sleep for ever", "import time\ntime.sleep(100)\n", expect={"TLE"})
    attack("fork bomb (Python)", "import os\nwhile True:\n    os.fork()\n", expect=STOPPED | {"WA"}, time_ms=3000)
    attack("fork bomb (shell)", "import os\nos.system('f() { f | f & }; f')\n", expect=STOPPED | {"WA", OK}, time_ms=3000)
    attack("thread bomb", "import threading, time\nwhile True:\n    threading.Thread(target=time.sleep, args=(60,)).start()\n", expect=STOPPED, time_ms=3000)
    attack("allocate 3 GB at once", "x = bytearray(3 * 1024 ** 3)\nprint(len(x))\n", expect={"MLE", "RE"})
    attack("allocate memory without end", "l = []\nwhile True:\n    l.append(b'x' * 10 ** 6)\n", expect={"MLE", "RE", "TLE"})
    attack("allocate memory without end (C)", "#include <stdlib.h>\n#include <string.h>\nint main(void){ for(;;){ char *p = malloc(1<<20); if(p) memset(p, 1, 1<<20); } }\n", "c", expect={"MLE", "RE", "TLE"})
    attack("allocate memory without end (Java)", "public class Main { public static void main(String[] a) { long[] x = new long[Integer.MAX_VALUE - 8]; System.out.println(x.length); } }\n", "java", expect={"MLE", "RE"}, time_ms=5000, mem=256)
    attack("print without end", "while True:\n    print('x' * 1000)\n", expect={"OLE"})
    attack("fill the disk", "f = open('big', 'wb')\nwhile True:\n    f.write(b'x' * 10 ** 6)\n", expect={"OLE", "RE"})
    attack("kill every process it can reach", "import os\nos.kill(-1, 9)\n", expect=STOPPED | {"WA"})
    attack("compile-time template explosion (C++)", "template<int N> struct F : F<N-1> {};\ntemplate<> struct F<0> {};\nF<100000> f;\nint main(){}\n", "cpp", expect={"CE"}, time_ms=3000)

    # --- SQL
    sql_attack("SQL: a query that grows without end", "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) SELECT x FROM c ORDER BY x DESC")
    sql_attack("SQL: open another database file", "ATTACH DATABASE '/tmp/oap-attached.db' AS z", check=lambda: "a database file was created" if os.path.exists("/tmp/oap-attached.db") else None)
    sql_attack("SQL: change the read-only setting", "PRAGMA query_only = OFF")
    sql_attack("SQL: load an extension", "SELECT load_extension('/tmp/x')")

    # --- afterwards the judge is as it was
    time.sleep(1)
    left_dirs = [d for d in os.listdir(work)] if os.path.isdir(work) else []
    alive = lambda: [p for p in psutil.process_iter(["uids", "status"]) if p.info["status"] != psutil.STATUS_ZOMBIE]  # dead processes waiting to be cleared do not count
    left_procs = [p.pid for p in alive() if p.info["uids"] and p.info["uids"].real >= base]
    results.append({"name": "afterwards: no run folder left", "ok": not left_dirs, "detail": f"{len(left_dirs)} left", "seconds": 0})
    results.append({"name": "afterwards: no run process left", "ok": not left_procs, "detail": f"{len(left_procs)} left", "seconds": 0})
    results.append({"name": "afterwards: process count back to normal", "ok": len(alive()) <= processes_before + 2, "detail": f"{processes_before} before, {len(alive())} after", "seconds": 0})
    sanity = local_judge_code({"time_limit_ms": 2000}, [{"id": "1", "ordinal": 1, "visibility": "open", "input": "2 3\n", "expected": "5", "weight": 1}], "python",
                              "a, b = map(int, input().split())\nprint(a + b)\n", "submit")
    results.append({"name": "afterwards: an honest program still passes", "ok": sanity["cases"][0]["verdict"] == "AC", "detail": sanity["cases"][0]["verdict"], "seconds": 0})
    os.remove(SECRET_FILE)

    width = max(len(r["name"]) for r in results)
    for r in results:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['name']:<{width}}  {r['detail']}  ({r['seconds']} s)")
    failed = [r for r in results if not r["ok"]]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed" + ("" if not failed else f": {len(failed)} FAILED"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
