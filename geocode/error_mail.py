"""Send mail to admin when an error happens."""

import logging
from logging import Formatter
from logging.handlers import SMTPHandler

import flask

PROJECT = "geocode"


class MySMTPHandler(SMTPHandler):
    """Custom SMTP handler to change mail subject."""

    def getSubject(self, record: logging.LogRecord) -> str:
        """Specify subject line for error mails."""
        subject = (
            f"{PROJECT} error: {record.exc_info[0].__name__}"
            if (record.exc_info and record.exc_info[0])
            else f"{PROJECT} error: {record.pathname}:{record.lineno:d}"
        )

        if qid := getattr(flask.g, "qid", None):
            subject += f" {qid}"

        if label := getattr(flask.g, "label", None):
            subject += f": {label}"

        return subject


class RequestFormatter(Formatter):
    """Custom logging formatter to include request."""

    def format(self, record: logging.LogRecord) -> str:
        """Record includes request."""
        record.request = flask.request
        return super().format(record)


def setup_error_mail(app: flask.Flask) -> None:
    """Send mail to admins when an error happens."""
    formatter = RequestFormatter(
        """
    Message type:       {levelname}
    Location:           {pathname:s}:{lineno:d}
    Module:             {module:s}
    Function:           {funcName:s}
    Time:               {asctime:s}
    GET args:           {request.args!r}
    URL:                {request.url}

    Message:

    {message:s}
    """,
        style="{",
    )

    mail_handler = MySMTPHandler(
        app.config["SMTP_HOST"],
        app.config["MAIL_FROM"],
        app.config["ADMINS"],
        app.name + " error",
        timeout=30,
    )
    mail_handler.setFormatter(formatter)

    mail_handler.setLevel(logging.ERROR)
    app.logger.propagate = True
    app.logger.addHandler(mail_handler)
