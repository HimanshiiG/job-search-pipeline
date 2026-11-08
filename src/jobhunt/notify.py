"""Send the newsletter (HTML + plain-text fallback) with its attachments.

dry_run (default) writes the email + attachments under output/ instead of sending, so the
pipeline is fully runnable without SMTP creds. Real send uses STARTTLS + env JOBHUNT_SMTP_PASS.
"""
from __future__ import annotations
import smtplib, ssl
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path


def deliver(email_cfg: dict, subject: str, text: str, html: str,
            attachments: list[tuple[str, str]], out_dir: Path, smtp_password: str | None,
            message_id: str | None = None) -> str:
    """message_id: set on the email so a reply's In-Reply-To ties it back to this letter."""
    maildir = out_dir / "email"
    maildir.mkdir(parents=True, exist_ok=True)
    (maildir / "newsletter.txt").write_text(text, encoding="utf-8")
    (maildir / "newsletter.html").write_text(html, encoding="utf-8")
    for name, content in attachments:
        (maildir / name).write_text(content, encoding="utf-8")

    if not email_cfg.get("enabled", True):
        return f"email disabled; newsletter written to {maildir}"
    if email_cfg.get("dry_run", True) or not smtp_password:
        why = "dry_run" if email_cfg.get("dry_run", True) else "no JOBHUNT_SMTP_PASS set"
        return f"email NOT sent ({why}); newsletter written to {maildir}"

    msg = EmailMessage()
    msg["Message-ID"] = message_id or make_msgid(domain="jobhunt.local")
    msg["Subject"] = f"{email_cfg.get('subject_prefix', '[JobHunt]')} {subject}"
    msg["From"] = email_cfg["from_addr"]
    msg["To"] = email_cfg["to_addr"]
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    for name, content in attachments:
        msg.add_attachment(content.encode("utf-8"), maintype="text", subtype="markdown", filename=name)

    ctx = ssl.create_default_context()
    with smtplib.SMTP(email_cfg["smtp_host"], int(email_cfg["smtp_port"])) as s:
        s.starttls(context=ctx)
        s.login(email_cfg["smtp_user"], smtp_password)
        s.send_message(msg)
    return f"newsletter sent to {email_cfg['to_addr']} with {len(attachments)} attachment(s)"
