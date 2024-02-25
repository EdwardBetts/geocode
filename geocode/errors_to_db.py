"""Save errors to the database."""

import logging
import traceback

import flask

from .database import session
from .model import ErrorLog


class DatabaseLoggingHandler(logging.Handler):
    """A logging handler that logs errors to a database."""

    def emit(self, record: logging.LogRecord) -> None:
        """Save log reord to database."""
        trace = None
        if record.exc_info:
            trace = traceback.format_exception(*record.exc_info)
        # request: flask.Request = record.request  # type: ignore
        request = flask.request
        error_log = ErrorLog(
            error_type=record.levelname,
            error_message=record.getMessage(),
            traceback="".join(trace) if trace else "No traceback available",
            context_info={
                "url": request.url,
                "args": dict(request.args),
                "endpoint": request.endpoint,
                "pathname": record.pathname,
                "lineno": record.lineno,
                "module": record.module,
                "funcName": record.funcName,
                "remote_addr": request.remote_addr,
            },
        )
        session.add(error_log)
        session.commit()


def setup_error_recorder(app: flask.Flask) -> None:
    """Save errors to the database."""
    db_handler = DatabaseLoggingHandler()
    db_handler.setLevel(logging.ERROR)
    app.logger.addHandler(db_handler)
