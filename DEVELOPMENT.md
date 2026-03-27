# NCC Development Guide

This repository is the active cloud-target control-plane repo for NCC.

The desktop-era GUI and legacy contract set have been quarantined under `legacy_desktop_archive/`. Active design authority now lives under `new_contracts/`.

---

## Active system shape

```text
Web browser
    |
    | HTTPS / WSS
    v
ncc-frontend  ->  ncc-backend  ->  core / Orchestrator  ->  ncc-agent  ->  game runtime
                                   ^
                                   |
                              game_system metadata
```

## Active repo areas

| Area | Role |
|---|---|
| `ncc-frontend/` | Web UI |
| `ncc-backend/` | Hosted API and control-plane surface |
| `core/` | Orchestrator and shared control logic |
| `ncc-agent/` | Machine-local execution agent |
| `plugins/` | Transitional game metadata/runtime area still used by the codebase |
| `new_contracts/` | Authoritative architecture, contracts, rules, and execution plan |

## Archived areas

These are historical and not the active product path:

- `legacy_desktop_archive/gui/`
- `legacy_desktop_archive/contracts/`
- `legacy_desktop_archive/PROJECT_BRAIN/`
- `legacy_desktop_archive/root/cli.py`

---

## Development priority

Follow:

- `new_contracts/IMPLEMENTATION_GAME_PLAN_v1.md`
- `new_contracts/AGENT_EXECUTION_RULES_v1.md`
- `new_contracts/PHASE_GATING_RULES_v1.md`

Current priority order:

1. host execution foundation
2. Orchestrator lifecycle correctness
3. ARK end-to-end cloud manageability
4. backend API completeness
5. frontend workflow
6. discovery/import
7. additional Steam games

---

## Contract authority

Use `new_contracts/` as the only authoritative contract set.

Start here:

- `new_contracts/00_REPO_ARCHITECTURE_OVERVIEW_v2.md`
- `new_contracts/IMPLEMENTATION_GAME_PLAN_v1.md`
- `new_contracts/governance/CORE_GOVERNANCE_STANDARD_v2.md`
- `new_contracts/backend/BACKEND_PUBLIC_API_CONTRACT_v1.md`
- `new_contracts/orchestrator/ORCHESTRATOR_LIFECYCLE_CONTRACT_v2.md`
- `new_contracts/game_system/GAME_DEFINITION_SCHEMA_CONTRACT_v1.md`
- `new_contracts/agent/HOST_AGENT_RUNTIME_EXECUTION_CONTRACT_v1.md`

---

## Testing

Run the smallest relevant scope first, then broader validation when practical.

Typical scopes:

### Core / Orchestrator

```bash
python -m pytest -q tests
```

### Backend

```bash
cd ncc-backend
pytest
```

### Agent

```bash
cd ncc-agent
pytest
```

### Frontend

Use the repo-standard frontend test/lint commands when applicable.

---

## Practical development rule

Do not spend time on legacy desktop surfaces unless the task explicitly targets the archive.

Do not build broad new abstractions before ARK works end to end through the cloud path.
