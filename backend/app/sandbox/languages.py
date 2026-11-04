"""One sandbox class per programming language. Each knows how to detect its toolchain,
compile a submission inside a work dir, and build the run command with its limits."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.core.config import get_settings
from app.sandbox.process import IS_WIN, ProcResult, clean_env, run_limited


@dataclass
class CompileResult:
    ok: bool
    message: str = ""
    time_ms: int = 0


class LanguageSandbox:
    key = ""
    name = ""
    monaco = ""
    filename = "main.txt"
    time_multiplier = 1.0
    memory_overhead_mb = 0      # added to the RSS limit (runtime baseline)
    use_rlimit_as = False       # Linux address-space cap (not usable for JVM / V8)
    rlimit_as_factor = 1        # cap = memory * factor + overhead (C/C++ use a loose cap, RSS decides MLE)
    nofile = 64

    # ---- toolchain
    def executables(self) -> Dict[str, Optional[str]]:
        raise NotImplementedError

    def version_cmd(self) -> List[str]:
        raise NotImplementedError

    def info(self, refresh: bool = False) -> Dict:
        cached = self.__dict__.get('_info')
        if cached is not None and not refresh:
            return cached
        exes = self.executables()
        missing = [k for k, v in exes.items() if not v]
        info = {"key": self.key, "name": self.name, "available": not missing, "executables": exes,
                "missing": missing, "version": "", "time_multiplier": self.time_multiplier}
        if not missing:
            try:
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    p = subprocess.run(self.version_cmd(), capture_output=True, text=True, timeout=30, cwd=td,
                                       env=self.env(td))
                v = (p.stdout or p.stderr or "").strip().splitlines()
                info["version"] = v[0] if v else ""
            except Exception as e:
                info["available"] = False
                info["missing"] = [f"version check failed: {e}"]
        self.__dict__['_info'] = info
        return info

    def available(self) -> bool:
        return bool(self.info()["available"])

    # ---- build & run
    def source_filename(self, source: str) -> str:
        return self.filename

    def write_source(self, workdir: str, source: str) -> str:
        fn = self.source_filename(source)
        with open(os.path.join(workdir, fn), "w", encoding="utf-8", newline="\n") as f:
            f.write(source)
        return fn

    def compile(self, workdir: str, source: str) -> CompileResult:
        self.write_source(workdir, source)
        return CompileResult(True)

    def run_cmd(self, workdir: str, source: str, memory_mb: int) -> List[str]:
        raise NotImplementedError

    def env(self, workdir: str) -> Dict[str, str]:
        exe_dirs = [os.path.dirname(p) for p in self.executables().values() if p]
        return clean_env(workdir, exe_dirs)

    def run(self, workdir: str, source: str, stdin: str, time_limit_ms: int, memory_mb: int,
            output_limit_kb: int = 1024) -> ProcResult:
        rl = memory_mb * self.rlimit_as_factor + self.memory_overhead_mb + 64 if self.use_rlimit_as else None
        return run_limited(self.run_cmd(workdir, source, memory_mb), cwd=workdir, stdin_text=stdin,
                           time_limit_ms=int(time_limit_ms * self.time_multiplier),
                           memory_mb=memory_mb + self.memory_overhead_mb, output_limit_kb=output_limit_kb,
                           env=self.env(workdir), rlimit_as_mb=rl, nofile=self.nofile)

    def _compile_with(self, workdir: str, cmd: List[str], timeout_ms: int = 30000) -> CompileResult:
        r = run_limited(cmd, cwd=workdir, time_limit_ms=timeout_ms, memory_mb=1536, output_limit_kb=256,
                        env=self.env(workdir), nofile=512, isolate_network=False, wall_factor=1.5)
        if r.error:
            return CompileResult(False, r.error, r.wall_ms)
        if r.timed_out:
            return CompileResult(False, "Compilation timed out", r.wall_ms)
        if r.exit_code != 0:
            msg = (r.stderr or r.stdout).replace(workdir + os.sep, "").replace(workdir, "")
            return CompileResult(False, msg.strip()[:4000] or f"compiler exited with {r.exit_code}", r.wall_ms)
        return CompileResult(True, (r.stderr or "").strip()[:2000], r.wall_ms)


def _which(configured: str, *names: str) -> Optional[str]:
    if configured:
        return configured if os.path.exists(configured) else shutil.which(configured)
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


# ------------------------------------------------------------------ Python
class PythonSandbox(LanguageSandbox):
    key, name, monaco, filename = "python", "Python 3", "python", "main.py"
    time_multiplier = 2.0
    memory_overhead_mb = 16
    use_rlimit_as = True

    def executables(self):
        return {"python": _which(get_settings().sandbox_python) or sys.executable}

    def version_cmd(self):
        return [self.executables()["python"], "--version"]

    def compile(self, workdir, source):
        self.write_source(workdir, source)
        try:
            compile(source, "main.py", "exec")  # syntax check only, nothing is executed
            return CompileResult(True)
        except SyntaxError as e:
            line = (e.text or "").rstrip()
            return CompileResult(False, f'File "main.py", line {e.lineno}\n    {line}\nSyntaxError: {e.msg}')

    def run_cmd(self, workdir, source, memory_mb):
        return [self.executables()["python"], "-I", "-S", "-B", "main.py"]


# ------------------------------------------------------------------ C / C++
class CSandbox(LanguageSandbox):
    key, name, monaco, filename = "c", "C (gcc, C17)", "c", "main.c"
    use_rlimit_as = True
    rlimit_as_factor = 4
    std = "-std=c17"
    tool_key, tool_setting, tool_names = "gcc", "sandbox_gcc", ("gcc",)

    def executables(self):
        return {self.tool_key: _which(getattr(get_settings(), self.tool_setting), *self.tool_names)}

    def version_cmd(self):
        return [self.executables()[self.tool_key], "--version"]

    def _exe(self):
        return "main.exe" if IS_WIN else "main"

    def compile(self, workdir, source):
        self.write_source(workdir, source)
        cmd = [self.executables()[self.tool_key], "-O2", self.std, "-o", self._exe(), self.filename]
        if IS_WIN:
            cmd.append("-static")
        cmd.append("-lm")
        return self._compile_with(workdir, cmd)

    def run_cmd(self, workdir, source, memory_mb):
        return [os.path.join(workdir, self._exe())]


class CppSandbox(CSandbox):
    key, name, monaco, filename = "cpp", "C++17 (g++)", "cpp", "main.cpp"
    std = "-std=c++17"
    tool_key, tool_setting, tool_names = "g++", "sandbox_gpp", ("g++",)


# ------------------------------------------------------------------ Java
class JavaSandbox(LanguageSandbox):
    key, name, monaco, filename = "java", "Java", "java", "Main.java"
    time_multiplier = 1.5
    memory_overhead_mb = 160
    nofile = 512

    def executables(self):
        s = get_settings()
        javac = _which(s.sandbox_javac, "javac")
        java = _which(s.sandbox_java, "java")
        if javac and not java:
            cand = os.path.join(os.path.dirname(javac), "java.exe" if IS_WIN else "java")
            java = cand if os.path.exists(cand) else None
        return {"javac": javac, "java": java}

    def version_cmd(self):
        return [self.executables()["javac"], "-version"]

    def main_class(self, source: str) -> str:
        m = re.search(r"public\s+(?:final\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)", source or "")
        return m.group(1) if m else "Main"

    def source_filename(self, source):
        return self.main_class(source) + ".java"

    def compile(self, workdir, source):
        fn = self.write_source(workdir, source)
        return self._compile_with(workdir, [self.executables()["javac"], "-encoding", "UTF-8", "-J-Xmx512m", fn],
                                  timeout_ms=60000)

    def run_cmd(self, workdir, source, memory_mb):
        return [self.executables()["java"], f"-Xmx{memory_mb}m", "-Xss64m", "-XX:+UseSerialGC",
                "-XX:TieredStopAtLevel=1", "-Dfile.encoding=UTF-8", "-cp", ".", self.main_class(source)]


# ------------------------------------------------------------------ JavaScript (Node.js)
class JavaScriptSandbox(LanguageSandbox):
    key, name, monaco, filename = "javascript", "JavaScript (Node.js)", "javascript", "main.js"
    time_multiplier = 1.5
    memory_overhead_mb = 64
    nofile = 256

    def executables(self):
        return {"node": _which(get_settings().sandbox_node, "node")}

    def version_cmd(self):
        return [self.executables()["node"], "--version"]

    def compile(self, workdir, source):
        self.write_source(workdir, source)
        r = run_limited([self.executables()["node"], "--check", self.filename], cwd=workdir, time_limit_ms=10000,
                        memory_mb=512, env=self.env(workdir), nofile=256, isolate_network=False)
        if r.exit_code not in (0, None) or r.timed_out:
            return CompileResult(False, (r.stderr or "syntax check failed").replace(workdir, "")[:4000], r.wall_ms)
        return CompileResult(True, "", r.wall_ms)

    def run_cmd(self, workdir, source, memory_mb):
        return [self.executables()["node"], f"--max-old-space-size={memory_mb}", self.filename]


# What a candidate's editor starts with when the question has no starter code of its own: never an empty editor.
SKELETON = {
    "python": "import sys\n\n# Read the input from standard input; print the answer with print(...)\ndata = sys.stdin.read().split()\n\n# write your code here\n",
    "java": "import java.util.*;\n\npublic class Main {\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);  // read the input\n        // write your code here\n        // print the answer with System.out.println(...)\n    }\n}\n",
    "cpp": "#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    // read the input with cin, print the answer with cout\n    // write your code here\n    return 0;\n}\n",
    "c": "#include <stdio.h>\n\nint main(void) {\n    /* read the input with scanf, print the answer with printf */\n    /* write your code here */\n    return 0;\n}\n",
    "javascript": "const input = require('fs').readFileSync(0, 'utf8').trim();  // the whole input\n\n// write your code here\n// print the answer with console.log(...)\n",
}

# A worked starter (the "sum of two numbers" question): the prompt for the AI shows it, and the seed uses it.
STARTER_SUM = {
    "python": "a, b = map(int, input().split())\n# TODO: print a + b\n",
    "java": "import java.util.*;\n\npublic class Main {\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);\n        long a = sc.nextLong(), b = sc.nextLong();\n        // TODO: print a + b\n    }\n}\n",
    "cpp": "#include <iostream>\nint main() {\n    long long a, b; std::cin >> a >> b;\n    // TODO: print a + b\n    return 0;\n}\n",
    "c": "#include <stdio.h>\nint main(void) {\n    long long a, b; scanf(\"%lld %lld\", &a, &b);\n    /* TODO: print a + b */\n    return 0;\n}\n",
    "javascript": "const [a, b] = require('fs').readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);\n// TODO: print a + b\n",
}

REGISTRY: Dict[str, LanguageSandbox] = {s.key: s for s in
                                         (PythonSandbox(), CSandbox(), CppSandbox(), JavaSandbox(), JavaScriptSandbox())}
ALIASES = {"py": "python", "python3": "python", "js": "javascript", "node": "javascript", "c++": "cpp",
           "java17": "java"}


def get_language(key: str) -> Optional[LanguageSandbox]:
    return REGISTRY.get(ALIASES.get((key or "").lower(), (key or "").lower()))


def refresh_all() -> List[Dict]:
    return [s.info(refresh=True) for s in REGISTRY.values()]
