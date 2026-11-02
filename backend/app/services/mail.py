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


def queue_mail(db: Session, to: str, subject: str, body: str, kind: str = "general",
               org_id: Optional[str] = None, send_after: Optional[datetime] = None) -> MailOutbox:
    m = MailOutbox(to=to, subject=subject, body=body, kind=kind, org_id=org_id, send_after=send_after)
    db.add(m)
    return m


def deliver_pending(db: Session) -> int:
    s = get_settings()
    n = 0
    rows = db.scalars(select(MailOutbox).where(MailOutbox.status == "queued").limit(50)).all()
    for m in rows:
        if m.send_after and aware(m.send_after) > now():
            continue
        if not s.smtp_host:
            m.status, m.sent_at = "logged", now()
            log.info("[mail:logged] to=%s subject=%s", m.to, m.subject)
            n += 1
            continue
        try:
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = s.smtp_from, m.to, m.subject
            msg.set_content(m.body)
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
                if s.smtp_tls:
                    smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
            m.status, m.sent_at = "sent", now()
            n += 1
        except Exception as e:  # keep retrying is pointless for config errors; mark failed
            m.status, m.error = "failed", str(e)[:500]
            log.warning("mail to %s failed: %s", m.to, e)
    db.commit()
    return n
