"""Resource-limited process runner used by every language sandbox (no Docker).

Isolation provided on every OS
  * fresh throw-away working directory per submission, deleted afterwards
  * scrubbed environment (no secrets, no proxy/JAVA_TOOL_OPTIONS leaks), TEMP/HOME inside the work dir
  * wall-clock and CPU time limits, memory limit (psutil RSS of the whole process tree),
    output limit (stdout/stderr go to files that are size-checked), whole process tree killed on breach
Extra on Linux
  * setrlimit: CPU, address space (native/Python), file size, core dumps, open files, number of processes; new session
  * inside the judge container (SANDBOX_UID_BASE set): every run is its own throw-away user, the work folder belongs to that user only,
    and everything the user started is killed when the run ends
  * optional network isolation with `unshare -rn` (SANDBOX_NETWORK_ISOLATION=auto|on|off)
Extra on Windows
  * new process group, no console window; C/C++ linked statically so no DLL search outside the work dir
"""
from __future__ import annotations

import itertools
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import psutil

from app.core.config import get_settings

IS_WIN = os.name == "nt"
_NET_ISOLATION: Optional[bool] = None


@dataclass
class ProcResult:
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    wall_ms: int = 0
    cpu_ms: int = 0
    peak_kb: int = 0
    timed_out: bool = False
    mem_exceeded: bool = False
    output_exceeded: bool = False
    error: str = ""
    extra: Dict = field(default_factory=dict)


_uids = itertools.count()
_uid_lock = threading.Lock()


def new_workdir(prefix: str = "run-") -> str:
    """A throw-away folder for one submission. In the judge container it belongs to a user of its own that nobody else can read or write as,
    numbered from SANDBOX_UID_BASE (a few runs are alive at once, so the numbers never collide)."""
    root = get_settings().sandbox_dir
    os.makedirs(root, exist_ok=True)
    wd = tempfile.mkdtemp(prefix=prefix, dir=root)
    base = get_settings().sandbox_uid_base
    if base and not IS_WIN:
        with _uid_lock:
            uid = base + next(_uids) % 10000
        os.chmod(wd, 0o700)
        os.chown(wd, uid, uid)
    return wd


def _run_uid(cwd: str) -> Optional[int]:
    """The user a run in this folder must take: the folder's owner, and only if that is one of the run users (never root)."""
    uid = os.stat(cwd).st_uid
    return uid if uid >= get_settings().sandbox_uid_base else None


def _kill_uid(uid: int) -> None:
    """Whatever a run left behind (a program that detached itself, a fork bomb) dies with the run. Killing them one by one cannot keep up with a
    fork bomb, so a helper becomes that user and has the kernel signal all of that user's processes at once; it repeats until none is left
    (dead ones waiting to be cleared do not count)."""
    def strike():
        os.setgroups([])
        os.setgid(uid)
        os.setuid(uid)
        os.kill(-1, signal.SIGKILL)
        os._exit(0)
    deadline = time.time() + 10
    while time.time() < deadline:
        subprocess.Popen(["true"], preexec_fn=strike).wait()
        if not any(p.info["uids"] and p.info["uids"].real == uid and p.info["status"] != psutil.STATUS_ZOMBIE
                   for p in psutil.process_iter(["uids", "status"])):
            return
        time.sleep(0.02)


def remove_workdir(path: str) -> None:
    for _ in range(5):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.1)  # Windows may hold a handle for a moment after kill


def clean_env(workdir: str, extra_path: Optional[List[str]] = None) -> Dict[str, str]:
    env = {"HOME": workdir, "TMP": workdir, "TEMP": workdir, "TMPDIR": workdir,
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "PYTHONDONTWRITEBYTECODE": "1", "NODE_OPTIONS": ""}
    path_parts = list(extra_path or [])
    if IS_WIN:
        for k in ("SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS",
                  "PROCESSOR_ARCHITECTURE"):
            if os.environ.get(k):
                env[k] = os.environ[k]
        env["USERPROFILE"] = workdir
        env["APPDATA"] = workdir
        env["LOCALAPPDATA"] = workdir
        sysroot = os.environ.get("SYSTEMROOT", r"C:\Windows")
        path_parts += [os.path.join(sysroot, "System32"), sysroot]
    else:
        path_parts += ["/usr/local/bin", "/usr/bin", "/bin"]
    env["PATH"] = os.pathsep.join(dict.fromkeys(p for p in path_parts if p))
    return env


def network_isolation_prefix() -> List[str]:
    """Linux only: return ['unshare','-rn'] when usable and enabled."""
    global _NET_ISOLATION
    mode = get_settings().sandbox_network_isolation.lower()
    if IS_WIN or mode == "off":
        return []
    if _NET_ISOLATION is None:
        exe = shutil.which("unshare")
        ok = False
        if exe:
            try:
                ok = subprocess.run([exe, "-rn", "true"], capture_output=True, timeout=5).returncode == 0
            except Exception:
                ok = False
        _NET_ISOLATION = ok
    if _NET_ISOLATION:
        return [shutil.which("unshare") or "unshare", "-rn"]
    return []


def _posix_limits(cpu_s: float, mem_mb: Optional[int], fsize_bytes: int, nofile: int, uid: Optional[int] = None, nproc: int = 256):
    def fn():  # runs in the child before exec
        import resource
        os.setsid()
        c = int(cpu_s) + 1
        resource.setrlimit(resource.RLIMIT_CPU, (c, c + 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
        resource.setrlimit(resource.RLIMIT_NPROC, (nproc, nproc))  # a fork bomb stops at this many processes of this user
        if mem_mb:
            b = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
        if uid is not None:  # last: from here on the program is an unprivileged user with no way back
            os.setgroups([])
            os.setgid(uid)
            os.setuid(uid)
    return fn


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        parent = psutil.Process(proc.pid)
        for ch in parent.children(recursive=True):
            try:
                ch.kill()
            except psutil.Error:
                pass
    except psutil.Error:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def _read(path: str, limit: int) -> str:
    try:
        with open(path, "rb") as f:
            data = f.read(limit)
        return data.decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def run_limited(cmd: List[str], cwd: str, stdin_text: str = "", time_limit_ms: int = 2000,
                memory_mb: int = 256, output_limit_kb: int = 1024, env: Optional[Dict[str, str]] = None,
                rlimit_as_mb: Optional[int] = None, nofile: int = 64, isolate_network: bool = True,
                wall_factor: float = 2.0, nproc: int = 256) -> ProcResult:
    """Run `cmd` with limits. memory_mb is enforced on the RSS of the whole process tree."""
    uid = None
    if not IS_WIN and get_settings().sandbox_uid_base:  # the judge container: never run as the service's own user
        uid = _run_uid(cwd)
        if uid is None:
            return ProcResult(error="sandbox: the work folder was not prepared for a separate user")
    io = os.path.join(cwd, "_io")
    os.makedirs(io, exist_ok=True)
    fin, fout, ferr = (os.path.join(io, n) for n in ("stdin.txt", "stdout.txt", "stderr.txt"))
    with open(fin, "w", encoding="utf-8", newline="") as f:
        f.write(stdin_text or "")
    out_limit = output_limit_kb * 1024
    cpu_s = time_limit_ms / 1000.0
    wall_limit = cpu_s * wall_factor + 1.0
    full = (network_isolation_prefix() if isolate_network else []) + list(cmd)
    res = ProcResult()
    kwargs: Dict = {}
    if IS_WIN:
        kwargs["creationflags"] = 0x00000200 | 0x08000000  # NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kwargs["preexec_fn"] = _posix_limits(cpu_s * 1.5 + 0.5, rlimit_as_mb, out_limit + 65536, nofile, uid, nproc)
    t0 = time.perf_counter()
    try:
        with open(fin, "rb") as si, open(fout, "wb") as so, open(ferr, "wb") as se:
            proc = subprocess.Popen(full, cwd=cwd, stdin=si, stdout=so, stderr=se, env=env, **kwargs)
            ps = None
            try:
                ps = psutil.Process(proc.pid)
            except psutil.Error:
                pass
            peak = 0
            cpu = 0.0
            while True:
                rc = proc.poll()
                elapsed = time.perf_counter() - t0
                if ps is not None and rc is None:
                    try:
                        procs = [ps] + ps.children(recursive=True)
                        rss = 0
                        c = 0.0
                        for p in procs:
                            try:
                                mi = p.memory_info()
                                rss += mi.rss
                                ct = p.cpu_times()
                                c += ct.user + ct.system
                            except psutil.Error:
                                pass
                        peak = max(peak, rss)
                        cpu = max(cpu, c)
                    except psutil.Error:
                        pass
                if rc is not None:
                    break
                if cpu > cpu_s or elapsed > wall_limit:
                    res.timed_out = True
                    _kill_tree(proc)
                    break
                if peak > memory_mb * 1024 * 1024:
                    res.mem_exceeded = True
                    _kill_tree(proc)
                    break
                try:
                    if os.path.getsize(fout) > out_limit or os.path.getsize(ferr) > out_limit:
                        res.output_exceeded = True
                        _kill_tree(proc)
                        break
                except OSError:
                    pass
                time.sleep(0.005 if elapsed < 0.2 else 0.015)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
            res.exit_code = proc.returncode
    except FileNotFoundError as e:
        res.error = f"executable not found: {e}"
        return res
    except Exception as e:  # pragma: no cover - unexpected OS error
        res.error = f"{type(e).__name__}: {e}"
        return res
    finally:
        if uid is not None:
            _kill_uid(uid)
    res.wall_ms = int((time.perf_counter() - t0) * 1000)
    res.cpu_ms = int(cpu * 1000) if cpu else res.wall_ms
    res.peak_kb = int(peak / 1024)
    try:  # a program that floods the output can end (file-size limit hit) before the loop above looks at the size
        res.output_exceeded = res.output_exceeded or os.path.getsize(fout) > out_limit or os.path.getsize(ferr) > out_limit
    except OSError:
        pass
    res.stdout = _read(fout, min(out_limit, 64 * 1024) + 1)
    res.stderr = _read(ferr, 8 * 1024)
    if not IS_WIN and res.exit_code is not None and res.exit_code < 0:
        import signal
        sig = -res.exit_code
        if sig in (signal.SIGXCPU,):
            res.timed_out = True
        elif sig == signal.SIGXFSZ:
            res.output_exceeded = True
        res.extra["signal"] = sig
    if res.cpu_ms > time_limit_ms:
        res.timed_out = True
    return res
