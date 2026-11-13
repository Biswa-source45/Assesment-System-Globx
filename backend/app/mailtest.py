"""Sends one small test mail with the server's mail settings, to check the setup: `python -m app.mailtest someone@example.com`
(on the server: `docker compose exec api python -m app.mailtest someone@example.com`). Prints the reason when it fails; never prints the password."""
import sys
from email.message import EmailMessage

from app.core.config import get_settings
from app.services.mail import _connect


def main(to: str) -> int:
    s = get_settings()
    if not s.smtp_host:
        print("SMTP_HOST is empty: e-mail is not set up (mails are only kept in the Mail outbox).")
        return 1
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, "KAUTILYA mail test"
    msg.set_content("This is a test mail from KAUTILYA by GLOBX. If you can read it, report cards can be e-mailed from this server.")
    try:
        smtp = _connect(s)
        smtp.send_message(msg)
        smtp.quit()
    except Exception as e:
        print(f"Could not send: {type(e).__name__}: {e}")
        return 1
    print(f"Sent a test mail to {to} through {s.smtp_host}:{s.smtp_port} as {s.smtp_user or '(no login)'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else print("Usage: python -m app.mailtest someone@example.com") or 2)
