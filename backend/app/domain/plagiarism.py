"""Plagiarism detection (SRS Section 8): winnowing fingerprints for code/SQL, n-gram Jaccard for text."""
from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Sequence, Set, Tuple

KEYWORDS = {
    "python": "and as assert break class continue def del elif else except False finally for from global if import in "
              "is lambda None nonlocal not or pass raise return True try while with yield print input range len int str "
              "list dict set map sorted",
    "java": "abstract boolean break byte case catch char class continue default do double else enum extends final finally "
            "float for if implements import instanceof int interface long new null package private protected public "
            "return short static super switch this throw throws try void while String System out println Scanner Math",
    "c": "auto break case char const continue default do double else enum extern float for goto if int long register "
         "return short signed sizeof static struct switch typedef union unsigned void volatile while printf scanf include",
    "cpp": "auto bool break case catch char class const continue default delete do double else enum false float for if "
           "include int long namespace new nullptr private public return short sizeof static std struct switch template "
           "this true try typedef using vector void while cin cout endl string",
    "javascript": "break case catch class const continue default delete do else export false finally for function if "
                  "import in instanceof let new null return switch this throw true try typeof undefined var void while "
                  "console log require process Math",
    "sql": "select from where group by order having join left right inner outer on as and or not in is null distinct "
           "count sum avg min max limit offset union all case when then else end desc asc like between exists",
}
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|==|!=|<=|>=|&&|\|\||\+\+|--|->|::|\S")


def strip_comments(src: str, lang: str) -> str:
    if lang in ("python",):
        src = re.sub(r"#.*", "", src)
        src = re.sub(r'("""|\'\'\')[\s\S]*?\1', "", src)
    elif lang == "sql":
        src = re.sub(r"--.*", "", src)
        src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    else:
        src = re.sub(r"//.*", "", src)
        src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return src


def tokens(src: str, lang: str) -> List[str]:
    kws = set(KEYWORDS.get(lang, "").split())
    if lang == "sql":
        kws = {k.lower() for k in kws}
    out = []
    for t in _TOKEN.findall(strip_comments(src or "", lang)):
        tl = t.lower() if lang == "sql" else t
        if re.match(r"[A-Za-z_]", t):
            out.append(tl if tl in kws else "ID")
        elif re.match(r"\d", t):
            out.append("N")
        elif t[0] in "\"'":
            out.append("S")
        else:
            out.append(t)
    return out


def fingerprints(toks: Sequence[str], k: int = 5, w: int = 4) -> Set[int]:
    if len(toks) < k:
        return set()
    hashes = [int(hashlib.md5(" ".join(toks[i:i + k]).encode()).hexdigest()[:12], 16) for i in range(len(toks) - k + 1)]
    if len(hashes) <= w:
        return {min(hashes)}
    fp = set()
    for i in range(len(hashes) - w + 1):
        fp.add(min(hashes[i:i + w]))
    return fp


def longest_common_run(a: Sequence[str], b: Sequence[str]) -> int:
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def code_similarity(a_src: str, b_src: str, lang: str, exclude: Set[int] = frozenset()) -> Tuple[float, int, int]:
    ta, tb = tokens(a_src, lang), tokens(b_src, lang)
    if min(len(ta), len(tb)) < 30:
        return 0.0, 0, min(len(ta), len(tb))
    fa, fb = fingerprints(ta) - set(exclude), fingerprints(tb) - set(exclude)
    if not fa or not fb:
        return 0.0, 0, min(len(ta), len(tb))
    sim = len(fa & fb) / min(len(fa), len(fb))
    return round(sim, 3), longest_common_run(ta[:1500], tb[:1500]), min(len(ta), len(tb))


def text_similarity(a: str, b: str, n: int = 5) -> float:
    def grams(s):
        w = re.findall(r"[a-z0-9]+", re.sub(r"<[^>]+>", " ", (s or "").lower()))
        return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}, len(w)
    ga, la = grams(a)
    gb, lb = grams(b)
    if min(la, lb) < 20 or not ga or not gb:
        return 0.0
    return round(len(ga & gb) / len(ga | gb), 3)


def level(sim: float, high: float = 0.85, medium: float = 0.60) -> str:
    return "high" if sim >= high else "medium" if sim >= medium else "clear"
