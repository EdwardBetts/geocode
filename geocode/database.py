import flask
import sqlalchemy
from sqlalchemy import create_engine, func
from sqlalchemy.orm import scoped_session, sessionmaker

session = scoped_session(sessionmaker())


def init_db(db_url: str, echo: bool = False) -> None:
    """Initialise database."""
    session.configure(bind=get_engine(db_url, echo=echo))


def get_engine(db_url: str, echo: bool = False) -> sqlalchemy.engine.base.Engine:
    """Create an engine object."""
    return create_engine(db_url, pool_recycle=3600, echo=echo)


def init_app(app: flask.app.Flask, echo: bool = False) -> None:
    """Initialise database connection within flask app."""
    db_url = app.config["DB_URL"]
    session.configure(bind=get_engine(db_url, echo=echo))

    @app.teardown_appcontext
    def shutdown_session(exception: Exception | None = None) -> None:
        session.remove()


def now_utc():
    """Time in UTC via SQL."""
    return func.timezone("utc", func.now())
