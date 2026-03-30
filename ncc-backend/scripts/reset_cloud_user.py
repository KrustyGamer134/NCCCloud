"""
Delete cloud-side tenant data for a test Clerk user.

This removes the backend tenant and its tenant-scoped rows so a recreated Clerk
account can provision as a fresh cloud user again. It does not clear any
host-local agent state on the machine.

Usage (from ncc-backend/):
    python scripts/reset_cloud_user.py --email test@example.com
    python scripts/reset_cloud_user.py --user-id user_123 --confirm

Default behavior is dry-run preview only. Pass --confirm to delete.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
# Allow running from any working directory.
_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

import psycopg2
from psycopg2.extras import RealDictCursor

from core.settings import settings

_TENANT_SCOPED_TABLES = [
    "tenant_settings",
    "instances",
    "agents",
    "audit_logs",
    "users",
]


def _sync_url(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or delete cloud tenant data for a Clerk user.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--email", help="User email stored in the backend users table.")
    target.add_argument("--user-id", help="Clerk user_id / JWT sub stored in the backend users table.")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete the tenant and its tenant-scoped backend data.",
    )
    return parser.parse_args()


def _find_user(cur: RealDictCursor, *, email: str | None, user_id: str | None) -> dict | None:
    if email:
        cur.execute(
            """
            SELECT user_id, tenant_id::text AS tenant_id, email, role
            FROM users
            WHERE lower(email) = lower(%s)
            ORDER BY created_at DESC NULLS LAST
            LIMIT 1
            """,
            (email,),
        )
    else:
        cur.execute(
            """
            SELECT user_id, tenant_id::text AS tenant_id, email, role
            FROM users
            WHERE user_id = %s
            LIMIT 1
            """,
            (user_id,),
        )
    return cur.fetchone()


def _count_rows(cur: RealDictCursor, tenant_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in _TENANT_SCOPED_TABLES:
        cur.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE tenant_id = %s",  # noqa: S608
            (tenant_id,),
        )
        row = cur.fetchone() or {}
        counts[table] = int(row.get("n") or 0)
    return counts


def main() -> int:
    args = _parse_args()
    url = _sync_url(settings.database_url)

    try:
        conn = psycopg2.connect(url)
    except Exception as exc:
        print(f"ERROR: cannot connect to database: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        user = _find_user(cur, email=args.email, user_id=args.user_id)
        if user is None:
            target = args.email or args.user_id or ""
            print(f"No backend user found for target: {target}")
            return 1

        tenant_id = str(user["tenant_id"])
        counts = _count_rows(cur, tenant_id)

        print("=" * 60)
        print("Target backend user")
        print("=" * 60)
        print(f"user_id:   {user['user_id']}")
        print(f"email:     {user['email']}")
        print(f"role:      {user['role']}")
        print(f"tenant_id: {tenant_id}")
        print()
        print("Tenant-scoped rows")
        for table in _TENANT_SCOPED_TABLES:
            print(f"- {table}: {counts[table]}")
        print()
        print("Note: this does not clear host-local agent settings or files on the machine.")

        if not args.confirm:
            print()
            print("Dry run only. Re-run with --confirm to delete this tenant's cloud data.")
            conn.rollback()
            return 0

        cur.execute("DELETE FROM tenants WHERE tenant_id = %s", (tenant_id,))
        if cur.rowcount != 1:
            conn.rollback()
            print("ERROR: tenant delete did not affect exactly one row.", file=sys.stderr)
            return 1

        conn.commit()
        print()
        print("Deleted tenant and cascading tenant-scoped cloud data.")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"ERROR: reset failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
