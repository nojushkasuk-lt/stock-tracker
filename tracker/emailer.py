"""Sends alert emails through the site's own Gmail account (SMTP with an app password; standard library only).

Never sends model text unescaped: the HTML part escapes everything. Credentials come from config (.env /
host secrets) and are never logged.
"""

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from html import escape

from tracker import config


class EmailNotConfigured(RuntimeError):
    pass


@dataclass(frozen=True)
class Item:
    title: str
    body: str
    url: str  # absolute


def compose(to: str, items: list[Item], *, more: int = 0, base_url: str | None = None) -> EmailMessage:
    base = (base_url or config.BASE_URL).rstrip("/")
    subject = items[0].title if len(items) == 1 else f"{len(items) + more} new alerts: {items[0].title} and more"
    settings = f"{base}/settings#alerts"
    text = ["Stock Tracker alerts", ""]
    for it in items:
        text += [it.title, it.body, it.url, ""]
    if more:
        text += [f"{more} more on the Alerts page: {base}/alerts", ""]
    text += ["For information only. Not investment advice.",
             f"You get these because email alerts are on. Turn them off in Settings: {settings}"]

    rows = "".join(
        f'<tr><td style="padding:14px 0;border-bottom:1px solid #1C2A44">'
        f'<a href="{escape(it.url)}" style="color:#E8EEF8;font-weight:700;font-size:16px;text-decoration:none">{escape(it.title)}</a>'
        f'<div style="color:#AFC0D8;font-size:14px;line-height:1.6;margin-top:4px">{escape(it.body)}</div>'
        f'<a href="{escape(it.url)}" style="color:#7DB2FF;font-size:13px;font-weight:700">Open</a></td></tr>' for it in items)
    if more:
        rows += (f'<tr><td style="padding:14px 0"><a href="{escape(base)}/alerts" style="color:#7DB2FF;font-weight:700">'
                 f'{more} more on the Alerts page</a></td></tr>')
    html = (f'<div style="background:#0B1424;padding:24px;font-family:Arial,Helvetica,sans-serif">'
            f'<div style="max-width:560px;margin:0 auto;background:#121E33;border:1px solid #1C2A44;border-radius:14px;padding:22px 24px">'
            f'<div style="color:#7DB2FF;font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase">Stock Tracker alerts</div>'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0">{rows}</table>'
            f'<p style="color:#6F819C;font-size:12px;margin:18px 0 0">For information only. Not investment advice.<br>'
            f'You get these because email alerts are on. <a href="{escape(settings)}" style="color:#9AABC4">Turn them off in Settings</a>.</p>'
            f'</div></div>')

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((config.EMAIL_FROM_NAME, config.SMTP_USER))
    msg["To"] = to
    msg["List-Unsubscribe"] = f"<{settings}>"
    msg.set_content("\n".join(text))
    msg.add_alternative(html, subtype="html")
    return msg


class GmailSender:
    def __init__(self):
        if not config.email_ready():
            raise EmailNotConfigured("Set EMAIL_PROVIDER=gmail, SMTP_USER and SMTP_APP_PASSWORD.")
        self._smtp: smtplib.SMTP_SSL | None = None

    def __enter__(self):
        self._smtp = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=ssl.create_default_context(), timeout=30)
        self._smtp.login(config.SMTP_USER, config.SMTP_APP_PASSWORD)
        return self

    def send(self, msg: EmailMessage) -> None:
        self._smtp.send_message(msg)

    def __exit__(self, *exc):
        if self._smtp is not None:
            try:
                self._smtp.quit()
            except smtplib.SMTPException:
                pass
