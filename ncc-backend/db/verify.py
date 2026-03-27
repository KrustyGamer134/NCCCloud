"""
db/verify.py — quick sanity-check for the NCC backend database.

Connects to the database, lists every known table and prints its row count.
Use this during development to confirm migrations ran correctly and that seed
data landed as expected.

Usage (from ncc-backend/):
    python -m db.verify
    # or
    python db/verify.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running as a standalone script from the ncc-backend/ directory.
_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import AsyncSessionLocal

# Tables in dependency / creation order — mirrors 0001_initial.py
TABLES = [
    "tenants",
    "users",
    "agents",
    "instances",
    "audit_logs",
    "plugin_catalog",
]


async def verify() -> None:
    print("=" * 52)
    print("  NCC Backend — database verification")
    print("=" * 52)

    try:
        async with AsyncSessionLocal() as db:
            # 1. Confirm connectivity by fetching server version
            result = await db.execute(text("SELECT version()"))
            pg_version: str = result.scalar_one()
            # Trim verbose version string to first line only
            short_version = pg_version.split(",")[0]
            print(f"\n  Connected: {short_version}\n")

            # 2. Check which tables actually exist in the public schema
            exists_result = await db.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' "
                    "ORDER BY tablename"
                )
            )
            existing = {row[0] for row in exists_result.fetchall()}

            # 3. Row counts for each expected table
            col_w = max(len(t) for t in TABLES) + 2
            print(f"  {'Table':<{col_w}}  {'Rows':>8}  Status")
            print(f"  {'-' * col_w}  {'-' * 8}  {'-' * 10}")

            all_ok = True
            for table in TABLES:
                if table not in existing:
                    print(f"  {table:<{col_w}}  {'—':>8}  MISSING ✗")
                    all_ok = False
                    continue
                count_result = await db.execute(
                    text(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
                )
                count: int = count_result.scalar_one()
                print(f"  {table:<{col_w}}  {count:>8}  ok ✓")

            # 4. List any unexpected tables
            extra = existing - set(TABLES) - {"alembic_version"}
            if extra:
                print(f"\n  Extra tables (not in expected list): {sorted(extra)}")

            # 5. Show current Alembic head
            if "alembic_version" in existing:
                ver_result = await db.execute(
                    text("SELECT version_num FROM alembic_version")
                )
                rows = ver_result.fetchall()
                heads = [r[0] for r in rows]
                print(f"\n  Alembic head: {', '.join(heads)}")
            else:
                print("\n  alembic_version table not found — migrations not yet run")
                all_ok = False

            print()
            if all_ok:
                print("  Result: ALL TABLES PRESENT ✓")
            else:
                print("  Result: ONE OR MORE TABLES MISSING ✗")
            print("=" * 52)

    except Exception as exc:
        print(f"\n  ERROR: could not connect — {type(exc).__name__}: {exc}")
        print("  Make sure DATABASE_URL in .env is correct and Postgres is running.")
        print("=" * 52)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(verify())
