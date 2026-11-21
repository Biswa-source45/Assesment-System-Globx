"""The report card of one candidate for one exam: the data (one dict, used by the PDF and by the on-screen page, so they cannot disagree) and the PDF.

The card never carries an answer key: only a question's title, type, marks, score and status are used, never its options, model answer or reference solution."""
from __future__ import annotations

import io
import re
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Assignment, Attempt, Department, MailOutbox, Test, User, aware, now
from app.services.mail import queue_mail
from app.services.reports import NOT_BINNED, OUTCOME_LABEL, RESULT_LABEL, attempt_report, ranked_attempts

IST = timezone(timedelta(hours=5, minutes=30))  # ponytail: one fixed zone (the company's); a setting if another zone is ever needed
ASSETS = Path(__file__).resolve().parents[1] / "assets"
COMPANY = "GLOBX System & Network Pvt Ltd"
KIND = {"mcq_single": "Choice", "mcq_multi": "Choice", "short": "Written", "long": "Written", "coding": "Coding", "sql": "SQL"}


def is_real_email(addr: str) -> bool:
    """A login-only candidate has a made-up address (name@exam.local): nothing can be mailed to it."""
    a = (addr or "").strip().lower()
    return "@" in a and not a.endswith("@exam.local")


def _when(d) -> str:
    return aware(d).astimezone(IST).strftime("%d %b %Y, %H:%M IST") if d else ""


def _pct(score, top) -> float:
    return round(100 * (score or 0) / top, 1) if top else 0.0


def question_status(item: Dict) -> str:
    if item.get("status") == "review":
        return "Awaiting marking"
    if not item.get("answered"):
        return "Not answered"
    score, marks = item.get("score") or 0, item.get("marks") or 0
    return "Correct" if marks and score >= marks - 1e-9 else "Incorrect" if score <= 0 else "Partly correct"


def card_data(db: Session, at: Attempt) -> Dict[str, Any]:
    """Everything the report card shows. Candidate-safe: no options, no answers, no reference solutions."""
    rep = attempt_report(db, at, staff_view=False)
    t, u, asg = db.get(Test, at.test_id), db.get(User, at.candidate_id), db.get(Assignment, at.assignment_id)
    dept = db.get(Department, t.department_id) if t.department_id else None
    ranked = ranked_attempts(db, t.id)
    pcts = [_pct(a.total_score, a.max_score) for a in ranked if a.max_score]
    a = rep["attempt"]
    by_section: Dict[str, List[Dict]] = {}
    n = 0
    for q in rep["questions"]:
        n += 1
        by_section.setdefault(q["section_id"], []).append({"n": n, "title": q["title"], "kind": KIND.get(q["type"], "Other"), "marks": q["marks"],
                                                           "score": round(q["score"] or 0, 2), "status": question_status(q)})
    sections = [{"title": s["title"], "score": round(s["score"] or 0, 2), "max": s["max"], "percent": _pct(s["score"], s["max"]), "average": s["average"],
                 "questions": by_section.get(s["id"], [])} for s in rep["sections"]]
    kinds: Dict[str, List[float]] = {}
    for sec in sections:
        for q in sec["questions"]:
            k = kinds.setdefault(q["kind"], [0.0, 0.0])
            k[0] += q["score"]
            k[1] += q["marks"] or 0
    scored = [s for s in sections if s["max"]]
    highlights = []
    if len(scored) >= 2:
        best, worst = max(scored, key=lambda s: s["percent"]), min(scored, key=lambda s: s["percent"])
        if best["percent"] != worst["percent"]:
            highlights = [f"Strongest section: {best['title']} ({best['percent']:g}%).", f"Needs most attention: {worst['title']} ({worst['percent']:g}%)."]
    reason = at.submit_reason or ""
    note = OUTCOME_LABEL.get(reason, "") if reason in ("violation_limit", "face_violation", "admin_ended", "time_over") else ""
    allowed = t.duration_min + (asg.extra_time_min if asg else 0)
    return {"report_no": "RC-" + at.id[:8].upper(), "generated_at": _when(now()), "declared": bool(t.results_declared_at), "declared_at": _when(t.results_declared_at),
            "candidate": {"name": u.name or u.username or "Candidate", "login": u.username or "", "email": u.email if is_real_email(u.email) else ""},
            "exam": {"title": t.title, "department": dept.name if dept else "", "taken_at": _when(at.started_at), "submitted_at": _when(at.submitted_at),
                     "minutes_allowed": allowed, "minutes_taken": (a["seconds_taken"] or 0) // 60 if a["seconds_taken"] is not None else None, "pass_mark": t.cutoff or 0},
            "score": {"score": round(a["total_score"] or 0, 2), "max": a["max_score"] or 0, "percent": a["percent"], "result": a["result"], "result_label": RESULT_LABEL.get(a["result"], "")},
            "rank": a["rank"], "of": a["of"], "class_average": round(sum(pcts) / len(pcts), 1) if pcts else 0, "highest": max(pcts, default=0),
            "attempted": a["attempted"], "questions": a["questions"], "note": note,
            "sections": sections, "kinds": [{"kind": k, "score": round(v[0], 2), "max": round(v[1], 2)} for k, v in kinds.items()], "highlights": highlights}


# ---------------------------------------------------------------- the PDF
BLUE, INK, MUTED, LINE, PANEL = colors.HexColor("#1d4ed8"), colors.HexColor("#0f172a"), colors.HexColor("#64748b"), colors.HexColor("#e2e8f0"), colors.HexColor("#f8fafc")
GREEN, GREEN_BG, RED, RED_BG = colors.HexColor("#16a34a"), colors.HexColor("#dcfce7"), colors.HexColor("#dc2626"), colors.HexColor("#fee2e2")
AMBER, AMBER_BG, BLUE_BG = colors.HexColor("#b45309"), colors.HexColor("#fef3c7"), colors.HexColor("#dbeafe")
TONE = {"passed": (GREEN, GREEN_BG), "not_passed": (RED, RED_BG), "not_attempted": (AMBER, AMBER_BG)}
STATUS_TONE = {"Correct": (GREEN, GREEN_BG), "Partly correct": (AMBER, AMBER_BG), "Incorrect": (RED, RED_BG), "Not answered": (MUTED, PANEL), "Awaiting marking": (BLUE, BLUE_BG)}
W, H = A4
M = 36
FRAME_W = W - 2 * M
_fonts: Dict[str, str] = {}


def _register() -> Dict[str, str]:
    """Inter for text and Poppins for headings (the app's own fonts); plain Helvetica if the files are missing."""
    if _fonts:
        return _fonts
    try:
        for name, file in (("Inter", "Inter-Regular"), ("Inter-Bold", "Inter-Bold"), ("Inter-SemiBold", "Inter-SemiBold"), ("Poppins", "Poppins-SemiBold")):
            pdfmetrics.registerFont(TTFont(name, str(ASSETS / "fonts" / f"{file}.ttf")))
        pdfmetrics.registerFontFamily("Inter", normal="Inter", bold="Inter-Bold", italic="Inter", boldItalic="Inter-Bold")
        _fonts.update(body="Inter", bold="Inter-Bold", semi="Inter-SemiBold", head="Poppins")
    except Exception:
        _fonts.update(body="Helvetica", bold="Helvetica-Bold", semi="Helvetica-Bold", head="Helvetica-Bold")
    return _fonts


def _t(s: Any) -> str:
    """Text the font can print: a character it has no glyph for becomes "?", not an empty box."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    glyphs = getattr(pdfmetrics.getFont(_register()["body"]).face, "charToGlyph", None)
    return "".join(c if glyphs is None or ord(c) in glyphs else "?" for c in s)


def _clip(text: str, font: str, size: float, width: float) -> str:
    text = _t(text)
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "...", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "..."


def _wrap(text: str, font: str, size: float, width: float, lines: int) -> List[str]:
    words, out, cur = _t(text).split(" "), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(trial, font, size) <= width or not cur:
            cur = trial
        else:
            out.append(cur)
            cur = w
    out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = _clip(out[-1] + " ...", font, size, width)
    return [_clip(x, font, size, width) for x in out]


def _chip(c, x, y, text, fg, bg, font, size=7.5, pad=7, h=15):
    w = pdfmetrics.stringWidth(text, font, size) + 2 * pad
    c.setFillColor(bg)
    c.roundRect(x, y, w, h, h / 2, stroke=0, fill=1)
    c.setFillColor(fg)
    c.setFont(font, size)
    c.drawString(x + pad, y + h / 2 - size * 0.35, text)
    return w


class Hero(Flowable):
    """The candidate, the exam and the score ring. Its height follows the length of the name and of the exam title."""

    def __init__(self, d):
        super().__init__()
        self.d, f = d, _register()
        self.left = A4[0] - 2 * M - 190
        self.name = _wrap(d["candidate"]["name"], f["head"], 19, self.left - 30, 2)
        self.exam = _wrap(d["exam"]["title"], f["head"], 12, self.left - 30, 2)
        self.box = max(150, 24 + 22 + (len(self.name) - 1) * 23 + 17 + 28 + 17 + (len(self.exam) - 1) * 15 + 19 + 16)

    def wrap(self, aw, ah):
        self.width, self.height = aw, self.box
        return aw, self.box

    def draw(self):
        c, d, f, w, h = self.canv, self.d, _register(), self.width, self.box
        c.setFillColor(PANEL)
        c.setStrokeColor(LINE)
        c.roundRect(0, 0, w, h, 12, stroke=1, fill=1)
        y = h - 24
        c.setFillColor(MUTED)
        c.setFont(f["semi"], 7.5)
        c.drawString(20, y, "CANDIDATE")
        y -= 22
        c.setFillColor(INK)
        c.setFont(f["head"], 19)
        for i, ln in enumerate(self.name):
            c.drawString(20, y - i * 23, ln)
        y -= (len(self.name) - 1) * 23 + 17
        sub = " · ".join(x for x in (f"Login: {d['candidate']['login']}" if d["candidate"]["login"] else "", d["candidate"]["email"]) if x)
        c.setFillColor(MUTED)
        c.setFont(f["body"], 8.5)
        c.drawString(20, y, _clip(sub, f["body"], 8.5, self.left - 30))
        y -= 28
        c.setFont(f["semi"], 7.5)
        c.drawString(20, y, "EXAM")
        y -= 17
        c.setFillColor(BLUE)
        c.setFont(f["head"], 12)
        for i, ln in enumerate(self.exam):
            c.drawString(20, y - i * 15, ln)
        y -= (len(self.exam) - 1) * 15 + 19
        c.setFillColor(MUTED)
        c.setFont(f["body"], 8.5)
        c.drawString(20, y, _clip(" · ".join(x for x in (d["exam"]["department"], d["exam"]["taken_at"]) if x), f["body"], 8.5, self.left - 30))
        # the ring
        s = d["score"]
        cx, cy, r = w - 95, h / 2 + 12, 41
        fg, _bg = TONE.get(s["result"], (BLUE, BLUE_BG))
        c.setLineWidth(9)
        c.setStrokeColor(LINE)
        c.circle(cx, cy, r, stroke=1, fill=0)
        pct = max(0.0, min(100.0, float(s["percent"] or 0)))
        if pct > 0:
            c.setStrokeColor(fg)
            c.setLineCap(1)
            c.arc(cx - r, cy - r, cx + r, cy + r, startAng=90, extent=-3.599 * pct)   # clockwise from the top
            c.setLineCap(0)
        c.setFillColor(INK)
        c.setFont(f["head"], 20)
        c.drawCentredString(cx, cy - 4, f"{pct:g}%")
        c.setFillColor(MUTED)
        c.setFont(f["body"], 8)
        c.drawCentredString(cx, cy - 17, f"{s['score']:g} / {s['max']:g}")
        if s["result"] in TONE:
            fg, bg = TONE[s["result"]]
            label = s["result_label"].upper()
            wd = pdfmetrics.stringWidth(label, f["bold"], 8) + 24
            _chip(c, cx - wd / 2, cy - r - 34, label, fg, bg, f["bold"], 8, 12, 18)


class Tiles(Flowable):
    """Rank, class average, highest, time and questions attempted."""
    box = 54

    def __init__(self, d):
        super().__init__()
        e = d["exam"]
        taken = f"{e['minutes_taken']} min" if e["minutes_taken"] is not None else "-"
        self.items = [("RANK", f"{d['rank']} of {d['of']}" if d["rank"] else "-", ""), ("CLASS AVERAGE", f"{d['class_average']:g}%", ""), ("HIGHEST SCORE", f"{d['highest']:g}%", ""),
                      ("TIME TAKEN", taken, f"of {e['minutes_allowed']} min"), ("ATTEMPTED", f"{d['attempted']} of {d['questions']}", "questions")]

    def wrap(self, aw, ah):
        self.width, self.height = aw, self.box
        return aw, self.box

    def draw(self):
        c, f = self.canv, _register()
        gap = 8
        tw = (self.width - gap * 4) / 5
        for i, (label, value, sub) in enumerate(self.items):
            x = i * (tw + gap)
            c.setFillColor(colors.white)
            c.setStrokeColor(LINE)
            c.roundRect(x, 0, tw, self.height, 8, stroke=1, fill=1)
            c.setFillColor(MUTED)
            c.setFont(f["semi"], 6.5)
            c.drawString(x + 10, self.height - 16, label)
            c.setFillColor(INK)
            c.setFont(f["head"], 12.5)
            c.drawString(x + 10, self.height - 34, _clip(value, f["head"], 12.5, tw - 16))
            if sub:
                c.setFillColor(MUTED)
                c.setFont(f["body"], 7)
                c.drawString(x + 10, 6, sub)


class Bars(Flowable):
    """One bar per section with the class average marked."""
    def __init__(self, sections, average=True):
        super().__init__()
        self.sections, self.average, self.row = [s for s in sections if s["max"]], average, 30 if average else 22

    def wrap(self, aw, ah):
        self.width = aw
        return aw, self.row * len(self.sections) + 4

    def draw(self):
        c, f = self.canv, _register()
        bw = self.width - 230
        top = self.row * len(self.sections)
        for i, s in enumerate(self.sections):
            y = top - (i + 1) * self.row + 8
            c.setFillColor(INK)
            c.setFont(f["semi"], 9)
            c.drawString(0, y + 4, _clip(s["title"], f["semi"], 9, 175))
            x0 = 185
            c.setFillColor(LINE)
            c.roundRect(x0, y + 3, bw, 9, 4.5, stroke=0, fill=1)
            fill = bw * max(0, min(1, s["score"] / s["max"]))
            if fill > 0:
                c.setFillColor(BLUE)
                c.roundRect(x0, y + 3, max(fill, 9), 9, 4.5, stroke=0, fill=1)
            c.setFillColor(INK)
            c.setFont(f["bold"], 8.5)
            c.drawRightString(self.width, y + 5, f"{s['score']:g} / {s['max']:g}")
            if self.average:
                avg = bw * max(0, min(1, (s["average"] or 0) / s["max"]))
                c.setStrokeColor(INK)
                c.setLineWidth(1.6)
                c.line(x0 + avg, y, x0 + avg, y + 15)
                c.setFillColor(MUTED)
                c.setFont(f["body"], 6.5)
                c.drawRightString(self.width, y - 5, f"class average {s['average']:g}")


def _styles() -> Dict[str, ParagraphStyle]:
    f = _register()
    return {"h": ParagraphStyle("h", fontName=f["head"], fontSize=11.5, leading=15, textColor=INK, spaceBefore=14, spaceAfter=7, keepWithNext=1),
            "cell": ParagraphStyle("cell", fontName=f["body"], fontSize=8.2, leading=10.5, textColor=INK),
            "muted": ParagraphStyle("muted", fontName=f["body"], fontSize=8.2, leading=11.5, textColor=MUTED),
            "note": ParagraphStyle("note", fontName=f["body"], fontSize=8.6, leading=12.5, textColor=INK)}


def _question_table(sec: Dict, st: Dict) -> Table:
    f = _register()
    head = [Paragraph(f'<font name="{f["semi"]}" color="#64748b" size="7">{x}</font>', st["cell"]) for x in ("#", "QUESTION", "TYPE", "MARKS", "RESULT")]
    rows = [[Paragraph(f'<font name="{f["bold"]}">{escape(_t(sec["title"]))}</font>', st["cell"]), "", "", Paragraph(f'<font name="{f["bold"]}">{sec["score"]:g} / {sec["max"]:g}</font>', st["cell"]), ""], head]
    style = [("SPAN", (0, 0), (2, 0)), ("BACKGROUND", (0, 0), (-1, 0), BLUE_BG), ("TEXTCOLOR", (0, 0), (-1, 0), INK), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
             ("LINEBELOW", (0, 1), (-1, 1), 0.6, LINE), ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5), ("LEFTPADDING", (0, 0), (-1, -1), 6),
             ("RIGHTPADDING", (0, 0), (-1, -1), 6)]
    for i, q in enumerate(sec["questions"], start=2):
        fg, bg = STATUS_TONE.get(q["status"], (MUTED, PANEL))
        rows.append([Paragraph(str(q["n"]), st["cell"]), Paragraph(escape(_clip(q["title"], f["body"], 8.2, 250)), st["cell"]), Paragraph(q["kind"], st["cell"]),
                     Paragraph(f'{q["score"]:g} / {q["marks"]:g}', st["cell"]), Paragraph(f'<font name="{f["semi"]}" color="{fg.hexval().replace("0x", "#")}">{q["status"]}</font>', st["cell"])])
        style += [("LINEBELOW", (0, i), (-1, i), 0.4, LINE), ("BACKGROUND", (4, i), (4, i), bg)]
    t = Table(rows, colWidths=[26, FRAME_W - 26 - 62 - 62 - 92, 62, 62, 92], repeatRows=2)
    t.setStyle(TableStyle(style))
    return t


class _Numbered(canvas.Canvas):
    """Draws "Page x of y" and the footer once the page count is known."""

    def __init__(self, *a, meta=None, **k):
        super().__init__(*a, **k)
        self._saved, self.meta = [], meta or {}

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._footer(total)
            super().showPage()
        super().save()

    def _footer(self, total):
        f, m = _register(), self.meta
        self.setStrokeColor(LINE)
        self.setLineWidth(0.6)
        self.line(M, 40, W - M, 40)
        self.setFillColor(MUTED)
        self.setFont(f["body"], 6.8)
        self.drawString(M, 28, _clip(f"{m.get('report_no', '')}  ·  {COMPANY}  ·  Confidential: for the candidate named above", f["body"], 6.8, FRAME_W - 70))
        self.drawRightString(W - M, 28, f"Page {self._pageNumber} of {total}")
        self.drawString(M, 18, _clip(m.get("footer", ""), f["body"], 6.8, FRAME_W))


def _header(c, doc, d):
    f = _register()
    first = doc.page == 1
    c.saveState()
    if first:
        logo = ImageReader(str(ASSETS / "kautilya-lockup.png"))
        c.drawImage(logo, M, H - M - 36, width=36 * 900 / 230, height=36, mask="auto")
        c.setFillColor(BLUE)
        c.setFont(f["head"], 13)
        c.drawRightString(W - M, H - M - 12, "ASSESSMENT REPORT CARD")
        c.setFillColor(MUTED)
        c.setFont(f["body"], 7.5)
        c.drawRightString(W - M, H - M - 25, f"Report no. {d['report_no']}  ·  {d['generated_at']}")
        c.setStrokeColor(BLUE)
        c.setLineWidth(1.4)
        c.line(M, H - M - 46, W - M, H - M - 46)
        if not d["declared"]:
            _chip(c, W - M - 130, H - M - 44 + 8, "PREVIEW: NOT DECLARED YET", AMBER, AMBER_BG, f["bold"], 6.5, 8, 13)
    else:
        c.setFillColor(MUTED)
        c.setFont(f["semi"], 8)
        c.drawString(M, H - M - 4, _clip(f"{d['candidate']['name']}  ·  {d['exam']['title']}", f["semi"], 8, FRAME_W - 130))
        c.drawRightString(W - M, H - M - 4, f"Report card  ·  {d['report_no']}")
        c.setStrokeColor(LINE)
        c.line(M, H - M - 12, W - M, H - M - 12)
    c.restoreState()


def card_pdf(d: Dict[str, Any]) -> bytes:
    st, f = _styles(), _register()
    buf = io.BytesIO()
    footer = (f"Generated by KAUTILYA by GLOBX  ·  results declared on {d['declared_at']}" if d["declared"] else "Preview generated before the results were declared")         + "  ·  marks may be revised by the examiner"
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=M, bottomMargin=48, title=_t(f"Report card - {d['candidate']['name']} - {d['exam']['title']}"),
                          author="KAUTILYA by GLOBX", subject="Assessment report card")
    first = Frame(M, 48, FRAME_W, H - M - 48 - 56, id="first", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    later = Frame(M, 48, FRAME_W, H - M - 48 - 24, id="later", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="First", frames=[first], onPage=lambda c, dc: _header(c, dc, d), autoNextPageTemplate="Later"),
                          PageTemplate(id="Later", frames=[later], onPage=lambda c, dc: _header(c, dc, d))])
    story: List[Any] = [Hero(d), Spacer(1, 10), Tiles(d)]
    if d["note"]:
        story += [Spacer(1, 8), Paragraph(f'<font color="#b45309">{escape(_t(d["note"]))}</font>', st["note"])]
    if d["exam"]["pass_mark"] and d["score"]["result"] in ("passed", "not_passed"):
        story += [Spacer(1, 6), Paragraph(f'Pass mark for this exam: {d["exam"]["pass_mark"]:g} mark{"" if d["exam"]["pass_mark"] == 1 else "s"}.', st["muted"])]
    secs = [s for s in d["sections"] if s["max"]]
    if secs:
        story += [Paragraph("Performance by section", st["h"]), Bars(secs), Paragraph("The dark mark on each bar is the class average.", st["muted"])]
    if d["kinds"]:
        story += [Paragraph("By type of question", st["h"]), Bars([{"title": k["kind"], "score": k["score"], "max": k["max"], "average": 0} for k in d["kinds"]], average=False)]
    if d["highlights"]:
        story += [Paragraph("Highlights", st["h"])] + [Paragraph("•  " + escape(_t(x)), st["note"]) for x in d["highlights"]]
    story.append(Paragraph("Question-wise result", st["h"]))
    for sec in d["sections"]:
        if sec["questions"]:
            story += [KeepTogether([_question_table(sec, st)]) if len(sec["questions"]) <= 6 else _question_table(sec, st), Spacer(1, 10)]
    doc.build(story, canvasmaker=lambda *a, **k: _Numbered(*a, meta={"report_no": d["report_no"], "footer": footer}, **k))
    return buf.getvalue()


# ---------------------------------------------------------------- the mail with the PDF
def file_name(d: Dict[str, Any]) -> str:
    clean = lambda x: re.sub(r"[^A-Za-z0-9]+", "-", _t(x)).strip("-")[:40]  # noqa: E731
    return f"report-card-{clean(d['candidate']['name']) or 'candidate'}-{clean(d['exam']['title']) or 'exam'}.pdf"


def visible_to_candidate(t: Test, at: Attempt) -> str:
    """"" when the candidate may have this report card, else the plain reason."""
    if at.status != "evaluated":
        return "This result is not ready yet."
    if not t.results_declared_at:
        return "The results of this exam have not been declared yet."
    if not (t.settings or {}).get("show_result_to_candidate", True):
        return "The results of this exam are not shared with candidates."
    return ""


def report_attachment(db: Session, attempt_id: str) -> Tuple[str, bytes]:
    """The PDF a report-card mail carries, made now from the current marks. ValueError (a plain reason) when the result is no longer shared."""
    at = db.get(Attempt, attempt_id)
    if not at:
        raise ValueError("The attempt no longer exists.")
    reason = visible_to_candidate(db.get(Test, at.test_id), at)
    if reason:
        raise ValueError(reason)
    d = card_data(db, at)
    return file_name(d), card_pdf(d)


def report_mail_text(d: Dict[str, Any]) -> Tuple[str, str]:
    s = d["score"]
    where = get_settings().public_base_url.rstrip("/")
    lines = [f"Dear {d['candidate']['name']},", "", f"The results of '{d['exam']['title']}' have been declared. Your detailed report card is attached as a PDF.", ""]
    if s["result_label"] and s["result"] != "no_pass_mark":
        lines.append(f"Result: {s['result_label']}")
    lines += [f"Score: {s['score']:g} / {s['max']:g} ({s['percent']:g}%)", "", f"You can also sign in at {where} with your exam login to see it and download it again.", "",
              "KAUTILYA by GLOBX", COMPANY]
    return f"Your report card - {d['exam']['title']}", "\n".join(lines)


def queue_report_cards(db: Session, t: Test) -> Dict[str, int]:
    """One mail per evaluated candidate with a real e-mail address, never two for the same attempt. A mail that failed is queued again.
    Nothing is sent when the exam does not share results with candidates."""
    out = {"queued": 0, "requeued": 0, "already": 0, "no_email": 0}
    if not (t.settings or {}).get("show_result_to_candidate", True):
        return out
    ats = db.scalars(select(Attempt).where(Attempt.test_id == t.id, Attempt.status == "evaluated", NOT_BINNED)).all()
    have = {m.attach: m for m in db.scalars(select(MailOutbox).where(MailOutbox.kind == "report_card", MailOutbox.attach.in_([a.id for a in ats] or [""])))}
    for at in ats:
        u = db.get(User, at.candidate_id)
        if not is_real_email(u.email):
            out["no_email"] += 1
        elif at.id in have:
            if have[at.id].status == "failed":
                have[at.id].status, have[at.id].error = "queued", ""
                out["requeued"] += 1
            else:
                out["already"] += 1
        else:
            subject, body = report_mail_text(card_data(db, at))
            queue_mail(db, u.email, subject, body, "report_card", t.org_id).attach = at.id
            out["queued"] += 1
    return out


def mail_states(db: Session, t: Test, attempt_ids: List[str]) -> Tuple[Dict[str, str], str]:
    """attempt id -> status of its report-card mail, and the first error text of a failure."""
    rows = db.scalars(select(MailOutbox).where(MailOutbox.kind == "report_card", MailOutbox.attach.in_(attempt_ids or [""]))).all()
    return {m.attach: m.status for m in rows}, next((m.error for m in rows if m.status == "failed" and m.error), "")
