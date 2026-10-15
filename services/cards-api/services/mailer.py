"""Provider boundary. The dev adapter never sends or logs recipient/content."""
from typing import Protocol

import config


class Mailer(Protocol):
    enabled: bool

    def send(self, *, to: str, subject: str, body: str, html: str, unsubscribe_url: str | None) -> None: ...


class NoopMailer:
    enabled = False

    def send(self, **kwargs) -> None:
        pass


class SmtpMailer:
    enabled = True

    def send(self, *, to: str, subject: str, body: str, html: str, unsubscribe_url: str | None) -> None:
        import smtplib
        from email.message import EmailMessage
        if not config.SMTP_HOST or not config.SMTP_FROM:
            raise RuntimeError("SMTP host and sender are required")
        msg = EmailMessage()
        msg["From"] = config.SMTP_FROM
        msg["To"] = to
        msg["Subject"] = subject
        if unsubscribe_url:
            msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        msg.set_content(body)
        msg.add_alternative(html, subtype="html")
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
            smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)


def get_mailer() -> Mailer:
    if config.S10_MAILER == "smtp":
        return SmtpMailer()
    return NoopMailer()
