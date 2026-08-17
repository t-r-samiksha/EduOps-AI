import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

load_dotenv()

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

try:
    from pgvector.sqlalchemy import Vector

    @compiles(Vector, "sqlite")
    def _compile_vector_sqlite(type_, compiler, **kw):
        return "BLOB"
except ImportError:
    pass

db_url = os.environ.get("DATABASE_URL", "")
if not db_url or "your-project-ref" in db_url:
    db_url = "sqlite:///./test_eduops.db"

_engine = create_engine(db_url)
_TestingSessionLocal = sessionmaker(bind=_engine)


@pytest.fixture()
def db_session():
    """A session bound to a transaction that rolls back after each test."""
    if "sqlite" in str(_engine.url):
        Base.metadata.create_all(bind=_engine)
        session = _TestingSessionLocal()
        try:
            yield session
        finally:
            session.rollback()
            session.close()
    else:
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
