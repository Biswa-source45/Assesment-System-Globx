"""Mails to staff users: their login details, the e-mail-change code and the notice after a change. Same look as the exam login mail (tables and inline
styles only, so Gmail and Outlook show it the same)."""
from __future__ import annotations

import html
from typing import List, Optional, Tuple

from app.core.config import get_settings
from app.services.report_card import COMPANY

LOGIN_KIND, CODE_KIND = "staff_login", "email_change"
ROLE_NAME = {"super_admin": "Super Admin", "org_admin": "Org Admin", "test_creator": "Test Creator", "recruiter": "Recruiter", "evaluator": "Evaluator"}
MONO = "font-family:Consolas,'Courier New',monospace;font-weight:bold"
SMALL = "margin:14px 0 0 0;font-size:12px;color:#6b7280"


def app_link() -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/login"


def _page(title: str, rows: str, button: Optional[Tuple[str, str]] = None) -> str:
    e = html.escape
    btn = ""
    if button:
        btn = (f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0 6px 0"><tr><td bgcolor="#1f4e8c" style="border-radius:6px">'
               f'<a href="{e(button[1], quote=True)}" style="display:inline-block;padding:12px 26px;color:#ffffff;font-size:15px;font-weight:bold;text-decoration:none">{e(button[0])}</a></td></tr></table>'
               f'<p style="margin:0 0 6px 0;font-size:12px;color:#6b7280">Or copy this link into your browser: {e(button[1])}</p>')
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f3f5f9;font-family:Arial,Helvetica,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f5f9"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border:1px solid #dfe5ef;border-radius:8px">
<tr><td style="background:#1f4e8c;color:#ffffff;padding:18px 24px;border-radius:8px 8px 0 0;font-size:20px;font-weight:bold">KAUTILYA <span style="font-weight:normal;font-size:14px">by GLOBX</span></td></tr>
<tr><td style="padding:24px;font-size:14px;color:#1b2a41;line-height:21px"><div style="font-size:16px;font-weight:bold;margin-bottom:12px">{e(title)}</div>{rows}{btn}</td></tr>
<tr><td style="border-top:1px solid #dfe5ef;padding:14px 24px;font-size:12px;color:#6b7280">KAUTILYA by GLOBX &middot; {e(COMPANY)}</td></tr>
</table></td></tr></table></body></html>"""


def staff_login_mail(name: str, email: str, password: str, roles: List[str]) -> Tuple[str, str, str]:
    """(subject, text, HTML): the application link, the e-mail to sign in with and the password."""
    link, who = app_link(), (name or "").strip() or "there"
    role_text = ", ".join(ROLE_NAME.get(r, r) for r in roles)
    text = "\n".join([f"Dear {who},", "", f"An account has been made for you on KAUTILYA by GLOBX ({COMPANY}).", "",
                      "YOUR LOGIN", f"Email: {email}", f"Password: {password}", f"Your role: {role_text}", "",
                      f"Open the application: {link}",
                      "Sign in with the email and password above. Then open My profile (your name at the bottom left) and change your password.", "",
                      "Keep this mail private: it holds your password. If you did not expect it, ignore it and tell your administrator."])
    e = html.escape
    rows = (f'<p style="margin:0 0 14px 0">Dear {e(who)},</p><p style="margin:0 0 14px 0">An account has been made for you on KAUTILYA by GLOBX.</p>'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f5f9;border-radius:6px"><tr><td style="padding:14px 16px;font-size:15px;line-height:26px">'
            f'<div style="font-size:12px;font-weight:bold;color:#1f4e8c;letter-spacing:1px">YOUR LOGIN</div>Email: <span style="{MONO}">{e(email)}</span><br>'
            f'Password: <span style="{MONO}">{e(password)}</span><br>Your role: <b>{e(role_text)}</b></td></tr></table>'
            '<p style="margin:14px 0 0 0">Sign in with the email and password above. Then open <b>My profile</b> (your name at the bottom left) and change your password.</p>'
            f'<p style="{SMALL}">Keep this mail private: it holds your password. If you did not expect it, ignore it and tell your administrator.</p>')
    return "Your KAUTILYA login", text, _page("Your login", rows, ("Open KAUTILYA", link))


def email_code_mail(name: str, code: str, new_email: str, minutes: int) -> Tuple[str, str, str]:
    """Goes to the OLD address: whoever can read it may confirm the change."""
    who = (name or "").strip() or "there"
    text = (f"Dear {who},\n\nA change of the e-mail of your KAUTILYA account to {new_email} was asked for.\n\nYour code: {code}\nIt is valid for {minutes} minutes.\n\n"
            "If this was not you, ignore this mail: nothing changes without the code. Consider changing your password.")
    e = html.escape
    rows = (f'<p style="margin:0 0 12px 0">A change of the e-mail of your account to <b>{e(new_email)}</b> was asked for.</p>'
            f'<div style="font-size:28px;letter-spacing:6px;margin:8px 0;{MONO}">{e(code)}</div>'
            f'<p style="margin:0 0 12px 0">The code is valid for {minutes} minutes.</p>'
            f'<p style="{SMALL}">If this was not you, ignore this mail: nothing changes without the code. Consider changing your password.</p>')
    return "Your code to change your KAUTILYA e-mail", text, _page("Confirm the change of e-mail", rows)


def email_changed_mail(name: str, new_email: str) -> Tuple[str, str, str]:
    """Goes to the old address after the change, so a change nobody asked for is noticed."""
    who = (name or "").strip() or "there"
    text = f"Dear {who},\n\nThe e-mail of your KAUTILYA account was changed to {new_email}. From now on sign in with the new address.\nIf this was not you, tell your administrator at once."
    e = html.escape
    rows = (f'<p style="margin:0 0 12px 0">The e-mail of your account was changed to <b>{e(new_email)}</b>. From now on sign in with the new address.</p>'
            f'<p style="{SMALL}">If this was not you, tell your administrator at once.</p>')
    return "Your KAUTILYA e-mail was changed", text, _page("E-mail changed", rows)
