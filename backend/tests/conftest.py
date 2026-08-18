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

from sqlalchemy.pool import StaticPool

# ONE DATABASE FOR BOTH TESTS AND THE APP - a deliberate team decision (2026-08-18), not an
# oversight. `TEST_DATABASE_URL` is honoured if anyone sets it, but nothing requires it and
# there is no warning when it is absent: the team weighed the trade-off and chose the simpler
# single-project setup for the hackathon.
#
# WHAT THAT COSTS, so nobody has to rediscover it:
#
#   1. SEQUENCES ADVANCE ON REAL TABLES. Every test rolls back, so no rows persist - but a
#      Postgres rollback does NOT reset a sequence. A full run pushes the id counters on
#      users/remarks/notifications forward by a few thousand. Functionally harmless, visible
#      if anyone reads an id.
#   2. DO NOT RUN THE SUITE DURING A DEMO. A ~13-minute run competes with the live app for
#      the same pooled connections.
#   3. ONE UNREPRODUCIBLE FAILURE PER FULL RUN IS EXPECTED, and is not a bug. Isolation is a
#      savepoint that has to hold ONE pooled connection for a whole test, and pgbouncer
#      recycling a connection mid-test breaks that. Seen on 2026-08-18:
#      test_person_b_authz.py::test_teacher_can_still_create_remarks failed once in a full
#      run, then passed 8/8 alone, passed with its whole file, and passed in a clean full run
#      of 1287. Triage before investigating: re-run the one test, then its file, then the
#      suite. Green on all three means it was the connection, not the code.
#
# Switching later costs nothing in code - point TEST_DATABASE_URL at another Postgres (a
# second Supabase project, or a local `pgvector/pgvector` container) and run
# `alembic upgrade head` against it.
_test_url = os.environ.get("TEST_DATABASE_URL", "").strip()
_app_url = os.environ.get("DATABASE_URL", "").strip()

db_url = _test_url or _app_url
if not db_url or "your-project-ref" in db_url:
    db_url = "sqlite:///:memory:"
    _engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
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
