"""
scripts/db_verify.py — synchronous CLI sanity-check for the NCC backend DB.

Uses psycopg2 (sync) so it can be run as a plain script with no async runtime.

Usage (from ncc-backend/):
    python scripts/db_verify.py

Exit codes:
    0 — all expected tables are present
    1 — one or more tables are missing, or the DB is unreachable
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running from any working directory.
_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import psycopg2

from core.settings import settings

# Expected tables in schema order.
_TABLES = [
    "tenants",
    "users",
    "agents",
    "instances",
    "audit_logs",
    "plugin_catalog",
]

# Tables for which we also show per-status breakdowns.
_STATUS_TABLES = {"instances", "agents"}

# Column that holds the primary status for each status-table.
_STATUS_COL = {
    "instances": "status",
    "agents": "is_revoked",   # boolean, shown as True/False counts
}


def _sync_url(async_url: str) -> str:
    """Strip +asyncpg driver prefix so psycopg2 can parse the URL."""
    return async_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def main() -> int:  # returns exit code
    url = _sync_url(settings.database_url)

    print("=" * 56)
    print("  NCC Backend — database verification (sync)")
    print("=" * 56)

    try:
        conn = psycopg2.connect(url)
    except Exception as exc:
        print(f"\n  ERROR: cannot connect — {type(exc).__name__}: {exc}")
        print("  Check DATABASE_URL in .env and ensure PostgreSQL is running.")
        print("=" * 56)
        return 1

    conn.autocommit = True
    cur = conn.cursor()

    try:
        # Server version
        cur.execute("SELECT version()")
        pg_ver: str = cur.fetchone()[0].split(",")[0]
        print(f"\n  Connected: {pg_ver}\n")

        # Which tables exist?
        cur.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' ORDER BY tablename"
        )
        existing = {row[0] for row in cur.fetchall()}

        # ── Table summary ──────────────────────────────────────────────────
        col_w = max(len(t) for t in _TABLES) + 2
        print(f"  {'Table':<{col_w}}  {'Rows':>8}  Status")
        print(f"  {'-' * col_w}  {'-' * 8}  {'-' * 10}")

        all_ok = True
        for table in _TABLES:
            if table not in existing:
                print(f"  {table:<{col_w}}  {'—':>8}  MISSING ✗")
                all_ok = False
                continue

            cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            count: int = cur.fetchone()[0]
            print(f"  {table:<{col_w}}  {count:>8}  ok ✓")

        # ── Per-status breakdowns ──────────────────────────────────────────
        for table in _STATUS_TABLES:
            if table not in existing:
                continue
            col = _STATUS_COL[table]
            cur.execute(
                f"SELECT {col}, COUNT(*) AS n "  # noqa: S608
                f"FROM {table} GROUP BY {col} ORDER BY n DESC"
            )
            rows = cur.fetchall()
            if not rows:
                continue
            print(f"\n  {table}.{col} breakdown:")
            for value, n in rows:
                print(f"    {str(value):<20}  {n:>6}")

        # ── Extra / unexpected tables ──────────────────────────────────────
        extra = existing - set(_TABLES) - {"alembic_version"}
        if extra:
            print(f"\n  Extra tables (not in expected list): {sorted(extra)}")

        # ── Alembic revision ──────────────────────────────────────────────
        if "alembic_version" in existing:
            cur.execute("SELECT version_num FROM alembic_version")
            heads = [r[0] for r in cur.fetchall()]
            print(f"\n  Alembic head: {', '.join(heads)}")
        else:
            print("\n  alembic_version table not found — migrations not yet run")
            all_ok = False

        print()
        if all_ok:
            print("  Result: ALL TABLES PRESENT ✓")
        else:
            print("  Result: ONE OR MORE TABLES MISSING ✗")
        print("=" * 56)

        return 0 if all_ok else 1

    except Exception as exc:
        print(f"\n  ERROR during verification: {type(exc).__name__}: {exc}")
        print("=" * 56)
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
