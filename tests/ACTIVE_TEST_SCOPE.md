# Active Test Scope

Purpose: Clarifies which tests remain active after the desktop-era archive split.

## 1) Active tests stay in `tests/`

Tests remain active if they cover any of these:

- Orchestrator lifecycle behavior
- machine-local `AdminAPI` behavior still used behind the agent/runtime layer
- agent-relevant execution or reporting paths
- game metadata or handler behavior still used by the active codebase
- provisioning, install, runtime, snapshot, persistence, or RCON behavior

## 2) Transitional naming rule

Some active tests still use old names such as:

- `AdminAPI`
- `plugin`

Those tests are still active if they cover live code paths.

Do not archive a test only because its name reflects transitional terminology.

## 3) Archived tests

Desktop GUI and legacy CLI tests were moved to:

- `legacy_desktop_archive/tests/`

## 4) Archive rule

Archive a test only if it targets:

- archived desktop GUI code
- archived desktop CLI code
- archived historical contracts as the primary authority

Otherwise keep it active until the live code path is removed or replaced.
