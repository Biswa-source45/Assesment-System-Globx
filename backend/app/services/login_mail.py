"""The exam login mail (what a student receives: exam details, username, password, a link) and what the screen knows about each person's mail
(sent to which address, when, why not). The record is the mail itself in the outbox: nothing is kept on the participant that could go out of date."""
from __future__ import annotations

import html
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import MailOutbox, Test, aware
from app.services.attempts import proctoring_config
from app.services.report_card import COMPANY, _when, is_real_email

KIND = "exam_login"
WAITING = ("not_sent", "failed", "email_changed")  # people the "Send logins" button mails; queued and sent ones are left alone
NO_SMTP = "E-mail is not set up on this server, so nothing was sent."


def exam_link(test: Test) -> str:
    """The link in the mail: the login page, which carries on to this exam after sign-in. It holds no secret."""
    return f"{get_settings().public_base_url.rstrip('/')}/login?exam={test.id}"


def window_sentence(t: Test) -> str:
    """When the exam can be taken, in plain words (India time). Depends on whether the exam has dates."""
    if t.starts_at and t.ends_at:
        return f"You can join the exam at any time from {_when(t.starts_at)} to {_when(t.ends_at)}."
    if t.ends_at:
        return f"You can join the exam at any time until {_when(t.ends_at)}."
    if t.starts_at:
        return f"The exam opens on {_when(t.starts_at)}. You can join at any time after that."
    return "There is no fixed date for this exam. You can take it at a time that suits you, as soon as you have this mail."


def _timer_sentence(t: Test) -> str:
    extra = " Please start early enough to finish before the exam closes." if t.ends_at else ""
    return f"Once you press Start you have {t.duration_min} minutes. The timer cannot be paused, so start only when you can sit the whole exam without a break.{extra}"


def _prepare(t: Test) -> List[str]:
    p = proctoring_config(t)
    out = ["A laptop or desktop computer with Google Chrome or Microsoft Edge, and a steady internet connection. Close other programs and tabs."]
    if p.get("enabled") and p.get("webcam"):
        out.append("A working webcam and a quiet, well-lit room. Your face must stay in the camera view for the whole exam.")
    if p.get("enabled") and p.get("screen_share"):
        out.append("You will be asked to share your entire screen. Please allow it.")
    if p.get("enabled") and p.get("fullscreen"):
        out.append("The exam runs in full screen. Leaving it is recorded.")
    return out


def exam_login_mail(t: Test, name: str, username: str, password: str) -> Tuple[str, str, str]:
    """(subject, plain text, HTML) of the login mail. The HTML uses tables and inline styles only, so Gmail and Outlook show it the same."""
    link, window, timer, prepare = exam_link(t), window_sentence(t), _timer_sentence(t), _prepare(t)
    who = (name or "").strip() or "Candidate"
    desc = (t.description or "").strip()
    subject = f"Your login for {t.title}"
    text = "\n".join([
        f"Dear {who},", "",
        f'You have been registered for the online exam "{t.title}" by {COMPANY}.', "",
        "EXAM DETAILS", f"Exam: {t.title}", *([desc] if desc else []), f"Time allowed: {t.duration_min} minutes", f"When: {window}", "",
        "YOUR LOGIN", f"Username: {username}", f"Password: {password}", "",
        "HOW TO START", f"1. Open this link: {link}", "2. Sign in with the username and password above. You are taken to your exam.",
        f"3. Read the instructions and press Start. {timer}", "",
        "BEFORE YOU START", *[f"- {x}" for x in prepare], "",
        "Keep this mail private: it holds your password. If you did not expect it, ignore it and tell the exam organiser.", "",
        "KAUTILYA by GLOBX", COMPANY])
    e = html.escape
    rows = "".join(f'<tr><td style="padding:2px 0 2px 0;font-size:14px;color:#1b2a41;line-height:20px">&bull;&nbsp;{e(x)}</td></tr>' for x in prepare)
    page = f"""<!doctype html><html><body style="margin:0;padding:0;background:#f3f5f9;font-family:Arial,Helvetica,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f5f9"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border:1px solid #dfe5ef;border-radius:8px">
<tr><td style="background:#1f4e8c;color:#ffffff;padding:18px 24px;border-radius:8px 8px 0 0;font-size:20px;font-weight:bold">KAUTILYA <span style="font-weight:normal;font-size:14px">by GLOBX</span></td></tr>
<tr><td style="padding:24px">
<p style="margin:0 0 14px 0;font-size:15px;color:#1b2a41">Dear {e(who)},</p>
<p style="margin:0 0 18px 0;font-size:14px;color:#1b2a41;line-height:21px">You have been registered for the online exam <b>{e(t.title)}</b> by {e(COMPANY)}.</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #dfe5ef;border-radius:6px"><tr><td style="padding:14px 16px">
<div style="font-size:12px;font-weight:bold;color:#1f4e8c;letter-spacing:1px;margin-bottom:6px">EXAM DETAILS</div>
<div style="font-size:14px;color:#1b2a41;line-height:21px"><b>{e(t.title)}</b>{('<br>' + e(desc)) if desc else ''}<br>Time allowed: <b>{t.duration_min} minutes</b><br>{e(window)}</div>
</td></tr></table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;background:#f3f5f9;border-radius:6px"><tr><td style="padding:14px 16px">
<div style="font-size:12px;font-weight:bold;color:#1f4e8c;letter-spacing:1px;margin-bottom:6px">YOUR LOGIN</div>
<div style="font-size:15px;color:#1b2a41;line-height:26px">Username: <span style="font-family:Consolas,'Courier New',monospace;font-weight:bold">{e(username)}</span><br>Password: <span style="font-family:Consolas,'Courier New',monospace;font-weight:bold">{e(password)}</span></div>
</td></tr></table>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0 6px 0"><tr><td bgcolor="#1f4e8c" style="border-radius:6px"><a href="{e(link, quote=True)}" style="display:inline-block;padding:12px 26px;color:#ffffff;font-size:15px;font-weight:bold;text-decoration:none">Open your exam</a></td></tr></table>
<p style="margin:0 0 18px 0;font-size:12px;color:#6b7280">Or copy this link into your browser: {e(link)}</p>
<div style="font-size:12px;font-weight:bold;color:#1f4e8c;letter-spacing:1px;margin-bottom:6px">HOW TO START</div>
<p style="margin:0 0 16px 0;font-size:14px;color:#1b2a41;line-height:21px">Sign in with the username and password above and you are taken to your exam. Read the instructions and press <b>Start</b>. {e(timer)}</p>
<div style="font-size:12px;font-weight:bold;color:#1f4e8c;letter-spacing:1px;margin-bottom:6px">BEFORE YOU START</div>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin-bottom:18px">{rows}</table>
<p style="margin:0;font-size:12px;color:#6b7280;line-height:18px">Keep this mail private: it holds your password. If you did not expect it, ignore it and tell the exam organiser.</p>
</td></tr>
<tr><td style="border-top:1px solid #dfe5ef;padding:14px 24px;font-size:12px;color:#6b7280">KAUTILYA by GLOBX &middot; {e(COMPANY)}</td></tr>
</table></td></tr></table></body></html>"""
    return subject, text, page


# ---------------------------------------------------------------- what the screen shows about each person's mail
def mails_of(db: Session, assignment_ids: List[str]) -> Dict[str, List[MailOutbox]]:
    """The login mails of these assignments, newest first (one query)."""
    out: Dict[str, List[MailOutbox]] = {}
    if assignment_ids:
        for m in db.scalars(select(MailOutbox).where(MailOutbox.kind == KIND, MailOutbox.attach.in_(assignment_ids)).order_by(MailOutbox.created_at.desc())):
            out.setdefault(m.attach, []).append(m)
    return out


def _iso(d) -> Optional[str]:
    return aware(d).isoformat() if d else None


def mail_status(m: MailOutbox) -> Tuple[str, str]:
    """(queued | sent | failed, reason) of one mail. "Sent" means the mail server accepted it."""
    if m.status == "queued":
        return "queued", ""
    if m.status == "sent":
        return "sent", ""
    if m.status == "logged":  # no mail server was set up when it was tried
        return "failed", NO_SMTP
    return "failed", m.error or "The mail could not be sent."


def mail_state(email: str, mails: List[MailOutbox]) -> Dict:
    """The newest login mail against the address the person has now: not_sent, queued, sent, failed, email_changed (it went to an older address, the
    new one has not been mailed) or no_email."""
    if not is_real_email(email):
        return {"state": "no_email", "to": "", "at": None, "error": ""}
    if not mails:
        return {"state": "not_sent", "to": "", "at": None, "error": ""}
    m = mails[0]
    status, why = mail_status(m)
    out = {"state": status, "to": m.to, "at": _iso(m.sent_at or m.created_at), "error": why}
    if m.to.strip().lower() != email.strip().lower():
        out["state"] = "email_changed"
    return out


def history(mails: List[MailOutbox]) -> List[Dict]:
    out = []
    for m in mails:
        status, why = mail_status(m)
        out.append({"to": m.to, "status": status, "queued_at": _iso(m.created_at), "sent_at": _iso(m.sent_at) if status == "sent" else None, "error": why})
    return out
