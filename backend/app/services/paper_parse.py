"""Read the clean parts of a question paper by rules, not by an AI.

A paper that numbers its questions (Q12.), lists options on lines of their own ((a) (b) (c) (d)), says the marks in brackets ([1 mark]) and gives
its answers (an "Answer:" line under the question, or an answer key at the end) can be read exactly: every question, option, picture, mark and
answer comes from the text, so nothing can be invented or put on the wrong question. Whatever does not read cleanly (coding, SQL, written answers,
a question without an answer, odd layouts) is handed back as a plain text block for the AI.

Pure functions on the text the reader made (pictures are `[[IMAGE n]]` markers in reading order)."""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Tuple

_Q = re.compile(r"(?m)^[ \t*#]*(?:Q|Question)\.?[ \t]*(\d{1,3})[ \t]*[.):]")
_OPTION = re.compile(r"^[ \t]*\(?([A-Za-z])[).:][ \t]*(.*)$")
_MARKER = re.compile(r"\[\[(IMAGE \d+)\]\]")
_LABEL = re.compile(r"(?i)\b(?:image|picture|figure|diagram)\s*:\s*")
_MARKS = re.compile(r"(?i)[\[(]\s*(\d+(?:\.\d+)?)\s*marks?\b([^\])]{0,80})[\])]")  # "[1 mark]" and "[1 mark; 0.5 off for a wrong answer]"
_NEG = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*(?:marks?\s*)?(?:off|deducted|deduction|negative)")
_ANSWER = re.compile(r"(?i)^[ \t*]*(?:(?:correct|model)\s+)?(?:answer|ans)\.?[ \t]*[:\-][ \t]*(.*)$")
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7}
_SAME = re.compile(r"(?i)\b(?:same|above|previous|given|earlier|preceding)\s+(?:\w+\s+){0,2}(?:chart|graph|figure|diagram|table|image|picture|map|tree|illustration)\b"
                   r"|\b(?:chart|graph|figure|diagram|table|image|picture|map|tree)\s+(?:above|given above|shown above)\b")
_EXPLAIN = re.compile(r"(?i)^[ \t*]*(?:explanation|solution|reason|rationale)[ \t]*[:\-][ \t]*")
_PASSAGE_INTRO = re.compile(r"(?i)^[ \t*]*(?:read the (?:following )?(?:passage|paragraph|text|extract)|directions?\b|passage\s*[:\-]|comprehension\b)")


def _letters(text: str, count: int) -> List[str]:
    """The option letters an answer names: "(b)", "b", "A, C", "(a) and (c)" (the first ones only: after them comes the option's own words)."""
    m = re.match(r"(?i)^\s*\(?([A-H])\)?(?:\s*(?:,|&|/|and)\s*\(?([A-H])\)?)*", text or "")
    if not m:
        return []
    found = re.findall(r"(?i)\b([A-H])\b|\(([A-H])\)", text[:m.end()])
    out = []
    for a, b in found:
        ch = (a or b).lower()
        if ch not in out and ord(ch) - 97 < count:
            out.append(ch)
    return out


def parse_key(key: str) -> Dict[int, List[str]]:
    """{question number: option letters} from an answer key: table cells "Q1 (c)" / "Q1 | (c)" and solution lines "Q12. Answer: (b) ...".
    The first answer found for a number wins."""
    out: Dict[int, List[str]] = {}
    for m in re.finditer(r"(?i)\bQ\s*(\d{1,3})\s*(?:[.:\-]\s*)?(?:answer|ans)\w*\s*[:\-]?\s*(\(?[A-H]\)?(?:\s*(?:,|&|and)\s*\(?[A-H]\)?)*)(?![A-Za-z])", key):
        out.setdefault(int(m.group(1)), _letters(m.group(2), 8))
    for m in re.finditer(r"\bQ\s*(\d{1,3})\s*[|:\-]?\s*\(([A-Ha-h](?:\s*[,&]\s*[A-Ha-h])*)\)", key):
        out.setdefault(int(m.group(1)), _letters(m.group(2), 8))
    return {k: v for k, v in out.items() if v}


def _plain_lines(lines: List[str]) -> List[str]:
    out = []
    for ln in lines:
        ln = _LABEL.sub("", _MARKER.sub(" ", ln))
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln:
            out.append(ln)
    return out


def _html(lines: List[str]) -> str:
    return "".join(f"<p>{html.escape(ln, quote=False)}</p>" for ln in lines)


def _read_block(number: int, text: str, key: Dict[int, List[str]]) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the question, "") when the block reads cleanly as a choice question with a known answer, else (None, the reason)."""
    raw_lines = text.split("\n")
    first = re.sub(r"^[ \t*#]*(?:Q|Question)\.?[ \t]*\d{1,3}[ \t]*[.):][ \t]*", "", raw_lines[0])
    lines = [first] + raw_lines[1:]
    opt_at = [i for i, ln in enumerate(lines) if i > 0 and _OPTION.match(ln) and not _MARKER.fullmatch(ln.strip())]
    # the options are the run of lines (a) (b) (c) ... starting at a, consecutive
    run: List[int] = []
    for i in opt_at:
        letter = _OPTION.match(lines[i]).group(1).lower()
        if letter == chr(97 + len(run)):
            run.append(i)
        elif run and letter == "a":
            break
    if len(run) < 2 or any(b - a > 3 for a, b in zip(run, run[1:])):
        return None, "no clean options"
    stem_lines, images, marks = lines[:run[0]], [], None
    stem_raw = "\n".join(stem_lines)
    images = _MARKER.findall(stem_raw)
    m = _MARKS.search(stem_raw)
    if m:
        marks = float(m.group(1))
    stem = _plain_lines([_MARKS.sub("", ln) for ln in stem_lines])
    if not stem or len(" ".join(stem)) < 3:
        return None, "no question text"
    options: List[Dict[str, str]] = []
    for k, start in enumerate(run):
        end = run[k + 1] if k + 1 < len(run) else len(lines)
        seg = lines[start:end]
        # an option is its own line (and the marker of its picture, on the line or right after); other lines after the last option are the tail
        extra = 1
        while extra < len(seg) and (_MARKER.search(seg[extra]) and not _plain_lines([seg[extra]])):
            extra += 1
        own, tail_seg = seg[:extra], [x for x in seg[extra:] if x.strip()]
        text0 = _OPTION.match(own[0]).group(2)
        picture = _MARKER.search(" ".join(own))
        label = _plain_lines([text0])
        opt = {"text": label[0] if label else ""}
        if picture:
            opt["image"] = picture.group(1)
        if not opt["text"] and "image" not in opt:
            return None, "an empty option"
        options.append(opt)
        if k == len(run) - 1:
            tail = tail_seg
        elif tail_seg:  # words between two options: not a layout we trust
            return None, "text between options"
    answers, explanation, passage, mode = None, [], [], None
    for ln in tail:
        text = ln.strip()
        if not text:
            continue
        a = _ANSWER.match(ln)
        if a and answers is None:
            answers = _letters(a.group(1), len(options))
            if not answers:  # "Answer: Paris" names the option by its words
                words = a.group(1).strip().lower()
                answers = [chr(97 + i) for i, o in enumerate(options) if o["text"].lower() == words]
            mode = "answer"
        elif _EXPLAIN.match(text):  # "Explanation: ..." up to the end of its sentence (it may wrap over lines)
            explanation.append(_EXPLAIN.sub("", text))
            mode = None if _TERM.search(text) else "explanation"
        elif _PASSAGE_INTRO.match(text):  # "Read the passage ..." and what follows belongs to the questions after this one
            passage.append(text)
            mode = "passage"
        elif mode == "passage":
            passage.append(text)
        elif mode == "explanation":
            explanation.append(text)
            mode = None if _TERM.search(text) else mode
        # anything else (the rest of a wrapped answer, stray text) is not part of this question
    if answers is None:
        for ln in stem_lines:
            a = _ANSWER.match(ln)
            if a:
                answers = _letters(a.group(1), len(options))
    if not answers:
        answers = key.get(number)
        answers = [x for x in (answers or []) if ord(x) - 97 < len(options)]
    if not answers:
        return None, "no answer in the paper"
    q: Dict[str, Any] = {"type": "mcq_multi" if len(answers) > 1 else "mcq_single", "title": "", "statement": question_html(join_wrapped(stem)), "options": options,
                         "correct": answers, "read_from_paper": True}
    if marks:
        q["marks"] = marks
    neg = _NEG.search(m.group(2)) if m else None
    if neg and float(neg.group(1)) > 0:
        q["negative_marks"] = float(neg.group(1))
    if images:
        q["images"] = list(dict.fromkeys(images))
    q["_tail"] = "\n".join(_plain_lines(passage))
    q["_solution_images"] = list(dict.fromkeys(_MARKER.findall("\n".join(tail))))  # a picture under the answer shows the solution: never a picture of the question
    if explanation:
        q["explanation"] = " ".join(explanation).strip()
    _, asked = split_question(join_wrapped(stem))
    if asked:
        words = asked.split()
        q["title"] = " ".join(words[:10]) + ("..." if len(words) > 10 else "")
    return q, ""


_RUN_END = re.compile(r"(?i)^[ \t*]*$|^[ \t*#]*(?:(?:Q|Question)\.?[ \t]*[A-Za-z]?\d{1,3}|\d{1,3})[ \t]*[.):]|^[ \t*#]*(?:section|part)[ \t]+\w+[ \t]*[:.\-–—]"
                      r"|^[ \t*]*(?:(?:correct|model)\s+)?(?:answer|ans|explanation|solution)\b"
                      r"|^[ \t*]*(?:read the (?:following )?(?:passage|paragraph|text|extract)|directions?\b|passage\s*[:\-]|comprehension\b)")


def _split_options(text: str) -> str:
    """Options written side by side ("(a) x (b) y (c) z", or wrapped over lines) get a line each: the reader needs them on lines of their own.
    A run of options that is already one per line is left exactly as it is."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        if not re.match(r"[ \t]*\(?a[).][ \t]", lines[i]):
            out.append(lines[i])
            i += 1
            continue
        j = i + 1
        while j < len(lines) and not _RUN_END.match(lines[j]):
            j += 1
        run = lines[i:j]
        wrapped = any(not re.match(r"[ \t]*\(?[a-h][).][ \t]?", ln) for ln in run[1:])  # an option's text that carries on over the next line
        if wrapped or any(re.search(r"[ \t]\(?[b-h][).][ \t]", ln) for ln in run):  # or more than one option on a line
            joined, parts, letter = " ".join(x.strip() for x in run), [], "b"
            while (m := re.search(rf"[ \t]+(?=\(?{letter}[).][ \t])", joined)):
                parts.append(joined[:m.start()])
                joined, letter = joined[m.end():], chr(ord(letter) + 1)
            run = parts + [joined]
        out += run
        i = j
    return "\n".join(out)


def tidy_paper(text: str) -> str:
    """Layouts the rules cannot read, put into one they can: a marks note that wrapped over two lines is one line again, and side-by-side options are split."""
    for _ in range(2):
        text = re.sub(r"(\[\s*\d+(?:\.\d+)?\s*marks?\b[^\]\n]*)\n([^\]\n]*\])", r"\1 \2", text, flags=re.I)
    return _split_options(text)


def parse_paper(body: str, key: str, spans: List[Tuple[int, str]]) -> Dict[str, Any]:
    """{sections: [{title, items: [{kind: "mcq", question} | {kind: "block", text, number}]}], exact: number of questions read by rules}.
    `spans` are (offset, title) of the section headings in `body`. Papers without numbered questions give no items."""
    starts = [(m.start(), int(m.group(1))) for m in _Q.finditer(body)]
    if len(starts) < 2:
        return {"sections": [], "exact": 0}
    cuts = sorted([(o, "q", n) for o, n in starts] + [(o, "h", t) for o, t in spans])
    answers = parse_key(key)
    sections: List[Dict[str, Any]] = [{"title": "", "items": []}]
    shared = ""  # the tables and rows a section's introduction gives once for all its questions (a shared schema)
    for k, (offset, kind, value) in enumerate(cuts):
        end = next((c[0] for c in cuts[k + 1:]), len(body))
        if kind == "h":
            sections.append({"title": value, "items": []})
            shared = "\n".join(re.findall(r"(?is)\bCREATE\s+TABLE\b.*?;|\bINSERT\s+INTO\b.*?;", body[offset:end]))
            continue
        text = body[offset:end].rstrip()
        q, why = _read_block(value, text, answers)
        code = None if q else read_code_block(value, text, key_for(key, value), shared)
        sections[-1]["items"].append({"kind": "mcq", "question": q, "number": value} if q else {"kind": "code", "question": code, "number": value, "text": text} if code
                                     else {"kind": "block", "text": text, "number": value, "why": why, **({"context": shared} if shared and not re.search(r"(?im)^[ \t]*sample data", text) else {})})  # (a script question's own CREATE TABLE and INSERT lines are its answer and its checks, not its schema)
    # text after the last option of a question that is really a passage for the questions after it
    for sec in sections:
        items = sec["items"]
        for i, it in enumerate(items):
            if it["kind"] != "mcq":
                continue
            tail = it["question"].pop("_tail", "")
            if not tail:
                continue
            n = re.search(r"(?i)next\s+(\w+)\s+questions?", tail)
            count = _NUMBER_WORDS.get(n.group(1).lower()) if n else None
            gone = 0
            for later in items[i + 1:]:
                if later["kind"] != "mcq":
                    continue
                st = later["question"]["statement"]
                if count is None and not re.search(r"(?i)passage|paragraph|text|extract", st):
                    break
                later["question"]["statement"] = "<blockquote>" + _html(join_wrapped([ln for ln in tail.split("\n") if ln.strip()])) + "</blockquote>" + st
                gone += 1
                if count is not None and gone >= count:
                    break
    solution: List[str] = []
    for sec in sections:
        for it in sec["items"]:
            if it["kind"] == "mcq":
                it["question"].pop("_tail", None)
                solution += it["question"].pop("_solution_images", [])
    sections = [s for s in sections if s["items"]]
    return {"sections": sections, "solution_images": solution, "exact": sum(1 for s in sections for it in s["items"] if it["kind"] in ("mcq", "code"))}


def share_pictures(questions: List[Dict[str, Any]]) -> None:
    """"Refer to the same bar chart": a question that says so and has no picture of its own gets the pictures of the nearest question before it that has."""
    last: Optional[List[str]] = None
    for q in questions:
        if q.get("images"):
            last = q["images"]
        elif last and _SAME.search(re.sub(r"<[^>]+>", " ", str(q.get("statement") or ""))):
            q["images"] = list(last)


# ---- coding and SQL questions: the code in them is copied, never written by an AI
_LANG = {"python": "python", "python3": "python", "py": "python", "java": "java", "c++": "cpp", "cpp": "cpp", "c": "c", "javascript": "javascript", "js": "javascript", "node": "javascript", "flask": "flask", "fastapi": "flask"}
_NOISE =re.compile(r"(?m)^[ \t]*(?:\[the whole page is also shown[^\n]*\]|--- Page \d+ ---|\[\[IMAGE \d+\]\])[ \t]*\n?")
_HEAD_STOP = re.compile(r"(?i)^\s*(?:starter(?: code)?|sample answer|model answer|sample solution|reference (?:solution|answer|program|code)|test cases?|sample(?: input| output| cases?| data)?|tables?|answer|hidden data)\b[^\n]{0,40}$")


def key_for(key: str, number: Optional[int]) -> str:
    """The part of the answer key about question `number` ("Q26. ..." or "Q26 reference solution" up to the next question's), or the SQL part, or the end."""
    if number is not None:
        m = re.search(r"(?m)^[ \t]*Q\s*%d\b" % number, key)
        if m:
            nxt = next((x for x in re.finditer(r"(?m)^[ \t]*Q\s*(\d+)\b", key[m.end():]) if int(x.group(1)) != number), None)
            return key[m.start():m.end() + nxt.start()] if nxt else key[m.start():]
    sql = re.search(r"(?im)^[ \t]*(?:detailed solutions?[^\n]*\bsql\b[^\n]*|reference query)\b", key)  # an SQL solution is often not labelled with its number
    return key[sql.start():][:5000] if sql else key[-5000:]


def _reference_code(text: str) -> Optional[Tuple[str, str]]:
    """(language, program) after a line "Reference solution (Python)" / "Sample answer (Java):", up to the test-case table or the next heading."""
    m = re.search(r"(?im)^[ \t]*(?:reference|sample|model) (?:solution|answer|program|code)[ \t]*(?:\(([^)\n]*)\))?[ \t]*:?[ \t]*$", text)
    if not m:
        return None
    first = (m.group(1) or "").strip().lower().split()
    if m.group(0).strip().lower().startswith("model") and not (first and first[0] in _LANG):
        return None  # "Model answer (indicative):" or a bare "Model answer:" is a written answer, not a program
    lang = _LANG.get(first[0], "python") if first else "python"
    code: List[str] = []
    for ln in text[m.end():].split("\n")[1:] if text[m.end():].startswith("\n") else text[m.end():].split("\n"):
        # the code ends at the test cases, the next question, or another solution (a paper may give the same answer in two languages)
        if re.match(r"^#\s*Type\b|^\d+\s+(?:open|hidden)\b|^[ \t]*Q\s*\d+\s*[.:\-]|^[ \t]*(?:Detailed solutions?|Test cases?|Tests?[ \t]*:?[ \t]*$|starter(?: code)?[ \t]*\(|(?:reference|sample|model) (?:solution|answer|program|code)\b)", ln, re.I):
            break
        code.append(ln.rstrip())
    while code and not code[-1].strip():
        code.pop()
    src = "\n".join(code)
    return (lang, src) if src.strip() and len(src) < 20000 else None


def _starters(text: str) -> Dict[str, str]:
    """The code a candidate's editor opens with, one block per language: a line "Starter code (Python):" and the code under it (indentation kept), up to the
    next label or the test cases."""
    out: Dict[str, str] = {}
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        m = re.match(r"(?i)^[ \t]*starter(?: code)?[ \t]*\(([^)\n]*)\)[ \t]*:?[ \t]*$", ln)
        lang = _LANG.get(((m.group(1) if m else "").strip().lower().split() or [""])[0])
        if not lang:
            continue
        code: List[str] = []
        for nxt in lines[i + 1:]:
            if re.match(r"(?i)^[ \t]*(?:Test cases?|Tests?[ \t]*:?[ \t]*$|starter(?: code)?[ \t]*\(|(?:reference|sample|model) (?:solution|answer|program|code)\b|Q\s*\d+\s*[.:\-])", nxt):
                break
            code.append(nxt.rstrip())
        src = "\n".join(code).strip("\n")
        if src.strip() and len(src) < 20000:
            out.setdefault(lang, src + "\n")
    return out


def _inline_cases(text: str) -> List[Dict[str, str]]:
    """Cases written under a "Test cases:" line: "open: <input>" / "hidden: <input>" on one line, or the label alone (or numbered, "open 2:") with the input on the
    lines below it, up to the next label (an input of several lines, or a list of requests for an API question). A line that describes a case
    ("... -> result") is not an input: then nothing is read here and the AI is asked."""
    m = re.search(r"(?im)^[ \t]*test cases?[ \t]*:?[ \t]*$", text)
    out, many = [], False
    for ln in (text[m.end():].split("\n") if m else []):
        c = re.match(r"(?i)^[ \t]*(open|hidden|sample|private)(?:[ \t]*\d+)?[ \t]*:[ \t]?(.*)$", ln)
        if c:
            out.append({"input": c.group(2).rstrip(), "visibility": "hidden" if c.group(1).lower() in ("hidden", "private") else "open", "purpose": ""})
            many = not c.group(2).strip()
        elif many and ln.strip():
            out[-1]["input"] = (out[-1]["input"] + "\n" + ln.rstrip()).lstrip("\n")
    out = [c for c in out if c["input"].strip()]
    return [] if any(" -> " in c["input"] for c in out) else out


def read_code_block(number: int, text: str, key_snippet: str, shared: str = "") -> Optional[Dict[str, Any]]:
    """A coding or SQL question read by rules, or None. The statement, the tables and rows (SQL), the reference query or program come from the text
    (in the question, or in the answer key); test cases are read when written "open: ..." / "hidden: ...", otherwise left to the AI (`_cases_key`).
    `shared` is the schema and rows a section's introduction gives once (used when the question has no tables of its own). SQL hidden data may be written
    in the paper: INSERT statements under a "Hidden data:" line (or "Open data:" for one the candidate sees as a sample), one such line per dataset."""
    tail = "\n\n" + shared if shared and not re.search(r"(?i)\bCREATE\s+TABLE\b", text) else ""
    labels = list(re.finditer(r"(?im)^[ \t]*(hidden|open) data\b[^\n]*$", text))
    sample = (text[:labels[0].start()] if labels else text) + tail      # the first dataset: everything before the first "Hidden data:" or "Open data:" line
    extra = [(m.group(1).lower(), d) for k, m in enumerate(labels)
             if (d := "\n".join(re.findall(r"(?is)\bINSERT\s+INTO\b.*?;", text[m.end():labels[k + 1].start() if k + 1 < len(labels) else len(text)])))]
    text += tail
    lines = text.split("\n")
    head = re.sub(r"^[ \t*#]*(?:Q|Question)\.?[ \t]*\d{1,3}[ \t]*[.):][ \t]*", "", lines[0])
    marks = next((m for m in (_MARKS.search(ln) for ln in lines[:6]) if m), None)  # the question's first line, or a later one when the line wrapped
    title = _MARKS.sub("", head).strip(" -:\t")
    body = lines[1:]
    if len(title) > 90 or title.endswith(("?", ".")) or not body:  # the first line is the question itself, not a title
        body, title = [_MARKS.sub("", head)] + body, ""
    images = list(dict.fromkeys(_MARKER.findall(text)))
    clean_key = _NOISE.sub("", key_snippet)
    sql = re.search(r"(?is)\bCREATE\s+TABLE\b.*?;", text)
    ref = _reference_code(_NOISE.sub("", text)) or _reference_code(clean_key)
    statement: List[str] = []
    langs: List[str] = []
    for ln in body:
        if _MARKER.fullmatch(ln.strip()):
            continue
        lang_line = re.match(r"(?i)^[ \t]*languages?[ \t]*:[ \t]*(.+?)[ \t]*$", ln)  # "Language: Python / Java / C++ / C": the languages the question allows, not part of the text
        if lang_line and not langs:
            langs = list(dict.fromkeys(_LANG[w] for t in re.split(r"[/,]|\bor\b", lang_line.group(1)) if (w := (t.strip().lower().split() or [""])[0]) in _LANG))
            if langs:
                continue
        if _HEAD_STOP.match(ln) and (len(statement) >= 1) or re.match(r"(?i)^\s*(?:create\s+table|insert\s+into)\b", ln):
            break
        shown = _MARKS.sub("", _MARKER.sub("", ln))
        if shown.strip() or not ln.strip():  # (a line that was only the marks note is not part of the question)
            statement.append(shown)
    stmt = "\n".join(join_wrapped(statement)).strip()
    if not stmt:
        return None
    q: Dict[str, Any] = {"title": title, "statement": stmt, "read_from_paper": True}
    if marks:
        q["marks"] = float(marks.group(1))
    if images:
        q["images"] = images
    if sql:
        schema = "\n".join(re.findall(r"(?is)\bCREATE\s+TABLE\b.*?;", sample))
        data = "\n".join(re.findall(r"(?is)\bINSERT\s+INTO\b.*?;", sample))
        sel = None
        a = re.search(r"(?im)^[ \t]*(?:(?:model )?answer|reference query)[ \t]*:?[ \t]*$", sample)  # the format: "Answer:" and the query under it
        if a:
            q_lines = []
            for ln in sample[a.end():].strip("\n").split("\n"):
                if not ln.strip() or re.match(r"(?i)^[ \t]*(?:(?:hidden|open) data|checks?[ \t]*:?[ \t]*$)", ln):
                    break
                q_lines.append(ln)
            sel = "\n".join(q_lines).strip() if q_lines else None
        if not sel:
            inserts = list(re.finditer(r"(?is)\bINSERT\s+INTO\b.*?;", sample))
            after_data = _NOISE.sub("", sample[inserts[-1].end():]) if inserts else ""  # a solution printed right under the question's data
            m = (re.search(r"(?is)\bSELECT\b.*?;", clean_key) or re.search(r"(?is)\bSELECT\b.*?;", _NOISE.sub("", sample[sample.lower().find("reference query"):]) if "reference query" in sample.lower() else "")
                 or re.search(r"(?is)\bSELECT\b.*?;", after_data))
            sel = m.group(0) if m else None
        c = re.search(r"(?im)^[ \t]*checks?[ \t]*:?[ \t]*$", sample)  # a script question (ALTER, INSERT, UPDATE, DELETE, DROP, CREATE): its statements, then the checks read the changed tables
        checks: List[str] = []
        for ln in (sample[c.end():].strip("\n").split("\n") if c else []):
            if not ln.strip() or re.match(r"(?i)^[ \t]*(?:hidden|open) data", ln):
                break
            checks.append(ln.strip().rstrip(";"))
        is_select = bool(sel and re.match(r"(?is)\s*(?:select|with)\b", sel))
        if not sel or not data or not (is_select or checks):  # DDL or DML without checks: not a one-query question: the AI makes it a script question
            return None
        q.update({"type": "sql", "schema": schema, "reference_sql": sel.rstrip(";").strip() if is_select else sel.strip(),
                  "datasets": [{"data": data, "visibility": "open"}] + [{"data": d, "visibility": v} for v, d in extra]})
        if checks and not is_select:
            q["checks"] = checks
        hint = re.search(r"(?im)^[ \t]*hidden data[ \t]*:[ \t]*(.+)$", text)
        if hint:
            q["_hint"] = hint.group(1).strip()
        note = re.search(r"(?im)^[ \t]*notes?\b.*$", text)  # a closing note stays with the question text
        if note:
            q["statement"] += "\n" + note.group(0).strip()
        return q
    if ref is None:
        return None
    q.update({"type": "coding", "reference": {"language": ref[0], "source": ref[1]}})
    if langs:
        q["languages"] = langs
    starters = _starters(_NOISE.sub("", text))
    if starters:
        q["starter"] = starters
    if ref[0] == "flask":  # a backend (API) question: only that language, and its time limit allows the framework to load
        q.update({"languages": ["flask"], "time_limit_ms": 5000})
    cases = _inline_cases(_NOISE.sub("", text))
    if cases:
        q["test_cases"] = cases
    elif re.search(r"(?im)^[ \t]*(?:open|hidden)[ \t]*\d*[ \t]*:", text):  # tests that are only described: the AI reads the whole question
        return None
    else:
        q["test_cases"] = []
        q["_cases_key"] = clean_key
    return q


_PAGE_LINES = re.compile(r"(?m)\n*^[ \t]*(?:\[the whole page is also shown[^\n]*\]|--- Page \d+ ---)[ \t]*\n?")


def clean_pages(text: str) -> str:
    """Remove the reader's own page lines ("--- Page 8 ---", "[the whole page is also shown ...]") so a question that crosses a page break reads as one.
    The blank line the reader leaves before a page line goes too: a query or a program cut by a page break is still one block."""
    return re.sub(r"\n{3,}", "\n\n", _PAGE_LINES.sub("\n", text))


def table_cases(key: str) -> List[Dict[str, str]]:
    """The test-case rows of an answer-key table that came out on one line: "1 open sample | {[()]} | YES | 1" (a row split over lines is left to the AI)."""
    out = []
    for m in re.finditer(r"(?m)^[ \t]*\d+[ \t]+(open|hidden)\b[^|\n]*\|[ \t]*([^|\n]+?)[ \t]*\|[ \t]*[^|\n]*\|[ \t]*\d+(?:\.\d+)?[ \t]*$", key, re.I):
        out.append({"input": m.group(2), "visibility": m.group(1).lower(), "purpose": ""})
    return out


_TERM = re.compile(r"[.?!:;]\s*$")
_LABELISH = re.compile(r"(?i)^(?:input|output|rules?|constraints?|sample|examples?|notes?|explanation|hint|tables?|answer|statements?|conclusions?|read the)\b")


def join_wrapped(lines: List[str]) -> List[str]:
    """PDF lines that only wrapped (the previous one does not end a sentence, neither is a label) are joined, so a question reads as paragraphs."""
    out: List[str] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            out.append("")
        elif out and out[-1] and not _TERM.search(out[-1]) and not _LABELISH.match(out[-1]) and not _LABELISH.match(s):
            out[-1] += " " + s
        else:
            out.append(s)
    return out


# ---- how a choice question reads: what is given in normal text, the question itself in bold
_LABEL_PARA = re.compile(r"(?i)^(?:statements?|conclusions?|assertion|reason|passage|directions?|read the|given|input|output|note)\b")
_ABBR = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Rs|St|vs|No|e\.g|i\.e|etc)\.")


def split_question(paragraphs: List[str]) -> Tuple[List[str], str]:
    """(the paragraphs before the question, the question): the last sentence of the last paragraph ("What is his rank from the bottom?"). A last
    paragraph that is itself a label line (Statements: ... Conclusions: ...) has no separate question."""
    paras = [p for p in paragraphs if p.strip()]
    if not paras or _LABEL_PARA.match(paras[-1]):
        return paras, ""
    protected = _ABBR.sub(lambda m: m.group(0).replace(".", "\x00"), paras[-1])
    parts = [x.replace("\x00", ".") for x in re.split(r"(?<=[.?!])\s+(?=[A-Z(\"'])", protected)]
    return paras[:-1] + ([" ".join(parts[:-1])] if len(parts) > 1 else []), parts[-1]


def question_html(paragraphs: List[str]) -> str:
    """The statement as HTML: the description as normal paragraphs, the question itself bold."""
    head, asked = split_question(paragraphs)
    return _html(head) + (f"<p><b>{html.escape(asked, quote=False)}</b></p>" if asked else "")
