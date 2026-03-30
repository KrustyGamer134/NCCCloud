"""
Delete host-local NCC settings for fresh-account testing on the same machine.

This clears local config/cache files that can make a newly provisioned cloud
account appear prefilled on a machine that has already been used before.

Default behavior is dry-run preview only. Pass --confirm to delete.

Usage (from repo root):
    python scripts/reset_local_host_state.py
    python scripts/reset_local_host_state.py --cluster-root E:\\NCCCloud --confirm
    python scripts/reset_local_host_state.py --confirm --include-agent-state
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or clear local host-side NCC settings for fresh-account testing.",
    )
    parser.add_argument(
        "--cluster-root",
        default=".",
        help="Cluster root containing cluster config, plugins/, and state/. Defaults to current directory.",
    )
    parser.add_argument(
        "--include-agent-state",
        action="store_true",
        help="Also delete ncc-agent/agent_state.json so the host must re-register the agent.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually delete the discovered local files.",
    )
    return parser.parse_args()


def _candidate_cluster_config_paths(cluster_root: Path) -> list[Path]:
    return [
        cluster_root / "cluster_config.json",
        cluster_root / "config" / "cluster_config.json",
    ]


def _candidate_plugin_defaults_paths(cluster_root: Path) -> list[Path]:
    plugins_root = cluster_root / "plugins"
    if not plugins_root.is_dir():
        return []
    paths: list[Path] = []
    for plugin_dir in sorted(path for path in plugins_root.iterdir() if path.is_dir()):
        paths.append(plugin_dir / "plugin_defaults.json")
        paths.append(plugin_dir / "plugin_config.json")
    return paths


def _candidate_dependency_state_paths(cluster_root: Path) -> list[Path]:
    return [cluster_root / "state" / "app_dependency_state.json"]


def _candidate_agent_state_paths(cluster_root: Path) -> list[Path]:
    return [cluster_root / "ncc-agent" / "agent_state.json"]


def _discover_paths(cluster_root: Path, *, include_agent_state: bool) -> list[Path]:
    candidates = [
        *_candidate_cluster_config_paths(cluster_root),
        *_candidate_plugin_defaults_paths(cluster_root),
        *_candidate_dependency_state_paths(cluster_root),
    ]
    if include_agent_state:
        candidates.extend(_candidate_agent_state_paths(cluster_root))
    return [path for path in candidates if path.exists() and path.is_file()]


def main() -> int:
    args = _parse_args()
    cluster_root = Path(args.cluster_root).resolve()
    if not cluster_root.exists() or not cluster_root.is_dir():
        print(f"ERROR: cluster root does not exist or is not a directory: {cluster_root}", file=sys.stderr)
        return 1

    targets = _discover_paths(cluster_root, include_agent_state=bool(args.include_agent_state))

    print("=" * 60)
    print("Local host-state reset preview")
    print("=" * 60)
    print(f"cluster_root: {cluster_root}")
    print(f"include_agent_state: {bool(args.include_agent_state)}")
    print()

    if not targets:
        print("No matching local host-state files found.")
        return 0

    print("Files targeted:")
    for path in targets:
        print(f"- {path}")

    print()
    print("This does not delete game server installs under gameservers_root.")
    print("This only removes local config/cache files that can repopulate settings for a new account.")

    if not args.confirm:
        print()
        print("Dry run only. Re-run with --confirm to delete these files.")
        return 0

    failures: list[tuple[Path, str]] = []
    removed = 0
    for path in targets:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            failures.append((path, str(exc)))

    print()
    print(f"Removed files: {removed}")
    if failures:
        print("Failures:")
        for path, message in failures:
            print(f"- {path}: {message}")
        return 1

    print("Local host-state reset complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
