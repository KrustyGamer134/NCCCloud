"""
Seed the plugin_catalog table with the ARK plugin (and any others found in the
NCC core plugins directory).

Upsert semantics
----------------
- INSERT when the plugin_id does not yet exist (available_in_plans set to
  _DEFAULT_PLANS).
- UPDATE when the plugin_id already exists: refresh display_name, description,
  and plugin_json, but DO NOT overwrite available_in_plans — any plan changes
  made via the admin UI or SQL are preserved.

Usage (from ncc-backend/):
    python scripts/seed_plugin_catalog.py

Exit codes:
    0 — success
    1 — any error (missing path, DB error, etc.)
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Ensure the package root is on sys.path when run as a standalone script.
_here = Path(__file__).resolve().parent.parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))

from sqlalchemy import select

from core.settings import settings
from db.models import PluginCatalog
from db.session import AsyncSessionLocal

# Plans assigned to a plugin when it is first inserted.
# Available_in_plans is NOT overwritten on subsequent runs.
_DEFAULT_PLANS: list[str] = ["free", "basic", "pro"]

# Plugins to seed.  Each tuple is (plugins/<dir_name>/plugin.json, description).
# Add entries here as new game plugins are introduced.
_PLUGIN_DIRS: list[tuple[str, str | None]] = [
    ("ark", "Dedicated server for ARK: Survival Ascended"),
]


async def _upsert_plugin(
    plugin_id: str,
    display_name: str,
    description: str | None,
    plugin_json: dict,
    default_plans: list[str],
) -> str:
    """
    Insert or update a plugin catalog entry.

    Returns "Inserted <plugin_id>" or "Updated <plugin_id>".
    Raises on any DB error.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(PluginCatalog).where(PluginCatalog.plugin_id == plugin_id)
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            # Refresh descriptive fields only — leave available_in_plans intact.
            existing.display_name = display_name
            existing.description = description
            existing.plugin_json = plugin_json
            db.add(existing)
            action = f"Updated {plugin_id}"
        else:
            db.add(
                PluginCatalog(
                    plugin_id=plugin_id,
                    display_name=display_name,
                    description=description,
                    plugin_json=plugin_json,
                    available_in_plans=default_plans,
                )
            )
            action = f"Inserted {plugin_id}"

        await db.commit()
        return action


async def main() -> None:
    ncc_core = Path(settings.ncc_core_path).resolve()

    if not ncc_core.is_dir():
        print(
            f"ERROR: NCC_CORE_PATH does not exist or is not a directory: {ncc_core}",
            file=sys.stderr,
        )
        sys.exit(1)

    plugins_root = ncc_core / "plugins"
    if not plugins_root.is_dir():
        print(
            f"ERROR: plugins/ directory not found at {plugins_root}",
            file=sys.stderr,
        )
        sys.exit(1)

    seeded = 0
    errors = 0

    for dir_name, description_override in _PLUGIN_DIRS:
        plugin_json_path = plugins_root / dir_name / "plugin.json"

        if not plugin_json_path.exists():
            print(
                f"WARNING: plugin.json not found at {plugin_json_path} — skipping",
                file=sys.stderr,
            )
            continue

        try:
            with plugin_json_path.open(encoding="utf-8") as fh:
                plugin_data: dict = json.load(fh)
        except Exception as exc:
            print(f"ERROR: failed to read {plugin_json_path}: {exc}", file=sys.stderr)
            errors += 1
            continue

        # game_id is the stable catalog identifier used in PLAN_LIMITS and API
        # responses (e.g. "ark_survival_ascended").  Fall back to "name" then the
        # directory name for plugins that don't define game_id.
        plugin_id: str = (
            plugin_data.get("game_id")
            or plugin_data.get("name")
            or dir_name
        )
        display_name: str = plugin_data.get("display_name") or plugin_id

        try:
            action = await _upsert_plugin(
                plugin_id=plugin_id,
                display_name=display_name,
                description=description_override,
                plugin_json=plugin_data,
                default_plans=_DEFAULT_PLANS,
            )
            print(action)
            seeded += 1
        except Exception as exc:
            print(
                f"ERROR: DB upsert failed for {plugin_id}: {exc}",
                file=sys.stderr,
            )
            errors += 1

    if errors:
        print(
            f"\n{errors} error(s) during seeding — see above.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\nDone — {seeded} plugin(s) seeded.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"ERROR: unexpected failure: {exc}", file=sys.stderr)
        sys.exit(1)
