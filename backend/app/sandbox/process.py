"""Resource-limited process runner used by every language sandbox (no Docker).

Isolation provided on every OS
  * fresh throw-away working directory per submission, deleted afterwards
  * scrubbed environment (no secrets, no proxy/JAVA_TOOL_OPTIONS leaks), TEMP/HOME inside the work dir
  * wall-clock and CPU time limits, memory limit (psutil RSS of the whole process tree),
    output limit (stdout/stderr go to files that are size-checked), whole process tree killed on breach
Extra on Linux
  * setrlimit: CPU, address space (native/Python), file size, core dumps, open files; new session
  * optional network isolation with `unshare -rn` (SANDBOX_NETWORK_ISOLATION=auto|on|off)
Extra on Windows
  * new process group, no console window; C/C++ linked statically so no DLL search outside the work dir
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
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


def new_workdir(prefix: str = "run-") -> str:
    root = get_settings().sandbox_dir
    os.makedirs(root, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=root)


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


def _posix_limits(cpu_s: float, mem_mb: Optional[int], fsize_bytes: int, nofile: int):
    def fn():  # runs in the child before exec
        import resource
        os.setsid()
        c = int(cpu_s) + 1
        resource.setrlimit(resource.RLIMIT_CPU, (c, c + 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
        if mem_mb:
            b = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
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
                wall_factor: float = 2.0) -> ProcResult:
    """Run `cmd` with limits. memory_mb is enforced on the RSS of the whole process tree."""
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
        kwargs["preexec_fn"] = _posix_limits(cpu_s * 1.5 + 0.5, rlimit_as_mb, out_limit + 65536, nofile)
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
    res.wall_ms = int((time.perf_counter() - t0) * 1000)
    res.cpu_ms = int(cpu * 1000) if cpu else res.wall_ms
    res.peak_kb = int(peak / 1024)
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
