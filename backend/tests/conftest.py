import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

load_dotenv()

from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402

_engine = create_engine(os.environ["DATABASE_URL"])
_TestingSessionLocal = sessionmaker(bind=_engine)


@pytest.fixture()
def db_session():
    """A session bound to a single connection/transaction that is rolled back after
    the test, so tests can freely commit (as request-scoped app code does) against
    the real Supabase DB without leaving data behind."""
    connection = _engine.connect()
    outer_transaction = connection.begin()
    session = _TestingSessionLocal(bind=connection)

    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, transaction):
        if transaction.nested and not transaction._parent.nested:
            sess.begin_nested()

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db_session):
    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)
