"""Send mail to admin."""

import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

import flask


def send_to_admin(subject: str, body: str) -> None:
    """Send an e-mail."""
    app = flask.current_app
    mail_from = app.config["MAIL_FROM"]
    msg = MIMEText(body, "plain", "UTF-8")

    msg["Subject"] = subject
    msg["To"] = ", ".join(app.config["ADMINS"])
    msg["From"] = f'{app.config["MAIL_FROM_NAME"]} <{app.config["MAIL_FROM"]}>'
    msg["Date"] = formatdate()
    msg["Message-ID"] = make_msgid()

    # extra mail headers from config
    for header_name, value in app.config.get("MAIL_HEADERS", {}).items():
        msg[header_name] = value

    s = smtplib.SMTP(app.config["SMTP_HOST"])
    s.sendmail(mail_from, app.config["ADMINS"], msg.as_string())
    s.quit()
