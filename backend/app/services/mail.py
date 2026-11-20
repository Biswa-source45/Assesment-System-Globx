"""Mail: everything goes to the outbox table; a background job delivers via SMTP when configured,
otherwise mails are marked 'logged' and are readable by admins in System > Mail outbox."""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import MailOutbox, aware, now

log = logging.getLogger("oap.mail")


SCRUBBED = "The login details were sent (or could not be sent) and have been removed from this record."


def queue_mail(db: Session, to: str, subject: str, body: str, kind: str = "general",
               org_id: Optional[str] = None, send_after: Optional[datetime] = None, html: Optional[str] = None) -> MailOutbox:
    m = MailOutbox(to=to, subject=subject, body=body, body_html=html, kind=kind, org_id=org_id, send_after=send_after)
    db.add(m)
    return m


def _message(db: Session, m: MailOutbox, sender: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, m.to, m.subject
    msg.set_content(m.body)
    if m.body_html:  # the plain text stays as the fallback for mail programs that show only text
        msg.add_alternative(m.body_html, subtype="html")
    if m.kind == "report_card" and m.attach:  # the PDF is made now, from the current marks; ValueError when the result is no longer shared
        from app.services.report_card import report_attachment
        name, pdf = report_attachment(db, m.attach)
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=name)
    return msg


def _connect(s):
    if s.smtp_user and not s.smtp_password:  # a mail server drops the connection at sign-in when there is no password: say so plainly
        raise RuntimeError("SMTP_PASSWORD is empty in the server settings (.env). Put the mail account's password there (for Gmail, the 16-letter app password) and restart the server.")
    smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30)
    try:
        if s.smtp_tls:
            smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
    except smtplib.SMTPAuthenticationError as e:
        smtp.close()
        said = e.smtp_error.decode("utf8", "replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
        raise RuntimeError(f"The mail server did not accept the user name and password (SMTP_USER, SMTP_PASSWORD). For Gmail use a 16-letter app password, typed without spaces. It said: {said}")
    except smtplib.SMTPServerDisconnected:
        smtp.close()
        raise RuntimeError("The mail server closed the connection while signing in. Check SMTP_USER and SMTP_PASSWORD (for Gmail, the 16-letter app password) and that this computer may reach smtp.gmail.com on port 587.")
    except Exception:
        smtp.close()
        raise
    return smtp


def deliver_pending(db: Session) -> int:
    """Sends the queued mails over one SMTP connection. A connection or login that fails (a wrong password) fails the whole batch at once with that
    reason, instead of trying again every ten seconds; one bad mail (a result no longer shared) fails alone."""
    s = get_settings()
    n = 0
    smtp = None
    rows = [m for m in db.scalars(select(MailOutbox).where(MailOutbox.status == "queued").limit(50)).all() if not (m.send_after and aware(m.send_after) > now())]
    try:
        for m in rows:
            if not s.smtp_host:
                m.status, m.sent_at = "logged", now()
                log.info("[mail:logged] to=%s subject=%s", m.to, m.subject)
                n += 1
                continue
            try:
                msg = _message(db, m, s.smtp_from)
                if smtp is None:
                    smtp = _connect(s)
                smtp.send_message(msg)
                m.status, m.sent_at = "sent", now()
                n += 1
            except (ValueError, smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError) as e:  # this mail only: no attachment can be made, or the address is refused
                m.status, m.error = "failed", (str(e) if isinstance(e, ValueError) else f"The mail server refused it: {e}")[:500]
            except Exception as e:
                reason = (str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}")[:500]  # RuntimeError: our own plain-language reason
                log.warning("mail to %s failed: %s", m.to, reason)
                for later in rows[rows.index(m):]:  # the server or the login is the problem: every mail waiting now fails with it
                    later.status, later.error = "failed", reason
                smtp = None
                break
    finally:
        for m in rows:  # a login mail holds a password: once it has been tried it is not kept (the address, times and reason stay as the record)
            if m.kind == "exam_login" and m.status != "queued":
                m.body, m.body_html = SCRUBBED, None
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:
                pass
        db.commit()
    return n
