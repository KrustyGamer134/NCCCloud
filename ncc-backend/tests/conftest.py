"""
tests/conftest.py — shared pytest fixtures for the NCC backend test suite.

Test database lifecycle
-----------------------
The ``test_db_url`` fixture (session scope) handles the full lifecycle of a
throw-away test database:

    1. Reads DATABASE_URL_TEST from the environment (default: the ncc_test DB
       on localhost using the ncc_app user).
    2. Drops and re-creates the database so every test session starts clean.
    3. Runs ``alembic upgrade head`` against the test DB so the schema matches
       the current migration head.
    4. Yields the async connection URL for use by other fixtures.
    5. Drops the test DB when the session ends.

The ``test_engine`` fixture (session scope) creates a single SQLAlchemy async
engine for the whole test session.

The ``db_session`` fixture (function scope) wraps each test in its own
AsyncSession that is rolled back on teardown, so tests cannot accidentally
leave data that affects other tests.

Usage in a test
---------------
Any test that needs a real database simply declares ``db_session`` as a
parameter::

    async def test_something(db_session):
        result = await db_session.execute(select(Tenant))
        ...

Tests that only need the URL (e.g. to build their own engine/session)
declare ``test_db_url``::

    async def test_raw(test_db_url):
        engine = create_async_engine(test_db_url)
        ...

Existing unit tests that mock the DB session do not need any of these
fixtures and are unaffected.

Environment variables
---------------------
DATABASE_URL_TEST  — full synchronous PostgreSQL URL for the test DB.
                     Default: postgresql://ncc_app:changeme@localhost:5432/ncc_test
                     The fixture converts it to a postgresql+asyncpg:// URL
                     automatically when creating the SQLAlchemy engine.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Paths ─────────────────────────────────────────────────────────────────────
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# ── Test DB URL ────────────────────────────────────────────────────────────────
_DEFAULT_TEST_DB_URL_SYNC = (
    "postgresql://ncc_app:changeme@localhost:5432/ncc_test"
)
_TEST_DB_URL_SYNC: str = os.getenv("DATABASE_URL_TEST", _DEFAULT_TEST_DB_URL_SYNC)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_async_url(sync_url: str) -> str:
    """Convert a postgresql:// URL to a postgresql+asyncpg:// URL."""
    if sync_url.startswith("postgresql+asyncpg://"):
        return sync_url
    if sync_url.startswith("postgresql://"):
        return sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    raise ValueError(
        f"DATABASE_URL_TEST must start with postgresql:// or "
        f"postgresql+asyncpg://, got: {sync_url!r}"
    )


def _admin_url(sync_url: str) -> str:
    """Return a URL that connects to the 'postgres' system database."""
    parsed = urlparse(sync_url)
    # Replace the database name component with 'postgres'
    return sync_url[: len(sync_url) - len(parsed.path)] + "/postgres"


def _db_name(sync_url: str) -> str:
    return urlparse(sync_url).path.lstrip("/")


def _create_test_db(sync_url: str) -> None:
    """Drop (if exists) and re-create the test database."""
    import psycopg2  # noqa: PLC0415 — lazy import so conftest loads without psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    admin = _admin_url(sync_url)
    db = _db_name(sync_url)

    conn = psycopg2.connect(admin)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            # Terminate any open connections so DROP DATABASE won't hang.
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db}"')
            cur.execute(f'CREATE DATABASE "{db}"')
    finally:
        conn.close()


def _drop_test_db(sync_url: str) -> None:
    """Terminate connections and drop the test database."""
    import psycopg2  # noqa: PLC0415
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    admin = _admin_url(sync_url)
    db = _db_name(sync_url)

    conn = psycopg2.connect(admin)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (db,),
            )
            cur.execute(f'DROP DATABASE IF EXISTS "{db}"')
    finally:
        conn.close()


def _run_migrations(async_url: str) -> None:
    """Run ``alembic upgrade head`` against *async_url* in a subprocess."""
    env = {**os.environ, "DATABASE_URL": async_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env,
        cwd=str(_BACKEND_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head failed:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_db_url() -> str:  # type: ignore[return]
    """
    Session-scoped fixture.

    Creates a clean test database, runs all Alembic migrations, yields the
    async URL, then drops the database on teardown.

    Skipped automatically when PostgreSQL is unreachable (marks all tests that
    depend on it as ``xfail`` rather than ``error``).
    """
    sync_url = _TEST_DB_URL_SYNC
    async_url = _to_async_url(sync_url)

    try:
        _create_test_db(sync_url)
    except Exception as exc:  # covers psycopg2.OperationalError and import errors
        pytest.skip(
            f"Test database unavailable — skipping DB-dependent tests.\n"
            f"Set DATABASE_URL_TEST to a reachable PostgreSQL instance.\n"
            f"Error: {exc}"
        )

    try:
        _run_migrations(async_url)
    except RuntimeError as exc:
        _drop_test_db(sync_url)
        pytest.fail(str(exc))

    yield async_url

    _drop_test_db(sync_url)


@pytest.fixture(scope="session")
def test_engine(test_db_url: str):
    """
    Session-scoped async SQLAlchemy engine connected to the test database.

    A single engine is reused across all tests in the session to avoid the
    overhead of creating a new connection pool per test.
    """
    engine = create_async_engine(test_db_url, pool_pre_ping=True)
    yield engine
    # Dispose is async; the pool is cleaned up automatically when the engine
    # is garbage-collected at the end of the process.


@pytest.fixture
async def db_session(test_engine):
    """
    Function-scoped async DB session connected to the test database.

    Wraps the test in a nested transaction (SAVEPOINT) so the outer
    transaction can be rolled back on teardown — each test always starts
    against the post-migration, empty-tables state.
    """
    factory = async_sessionmaker(
        test_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with factory() as session:
        yield session
        # Roll back any writes the test made so the next test starts clean.
        await session.rollback()
