# AGENTS.md

## Project
Cloud-based game server control plane with a host agent.

Primary active game system: ARK: Survival Ascended.

Canonical architecture:

Frontend
-> Backend API
-> Orchestrator
-> Game System
-> Host Agent
-> Game Runtime

## Boss preferences
- Default to Codex-style tasks unless explicitly told otherwise.
- Keep responses minimal unless clarification is requested.
- Prefer minimal patch-style edits over full rewrites.
- One fix path only.
- Keep tests green.

## Working style
- Assume full repo access.
- Inspect the repo directly before editing.
- Apply the smallest safe patch.
- Prefer targeted changes over broad rewrites.
- Do not make unrelated cleanup changes.
- Do not rename symbols unless required by the task.

## Critical path rules
- Follow `new_contracts/IMPLEMENTATION_GAME_PLAN_v1.md`.
- Follow `new_contracts/AGENT_EXECUTION_RULES_v1.md`.
- Follow `new_contracts/PHASE_GATING_RULES_v1.md`.
- Do not build the system backwards.

## Core architecture rules
- Orchestrator owns lifecycle authority.
- Backend API is the stable hosted facade.
- Frontend must route actions through backend API.
- Host Agent executes machine-local work only.
- Game System defines supported-game metadata and schemas.
- Do not bypass Orchestrator for lifecycle work.

## Frontend rules
- Frontend is presenter + action dispatcher only.
- Frontend must not own lifecycle legality.
- Frontend must not access host-local filesystem state directly.
- Frontend may normalize display state for presentation only.

## Backend rules
- Backend routes requests between frontend and the system.
- Backend must not take lifecycle authority away from Orchestrator.
- Backend may compose snapshots and route non-lifecycle actions through approved boundaries.

## Orchestrator rules
- Orchestrator is the lifecycle authority.
- Preserve canonical lifecycle states and transitions.
- Preserve stop/restart reconciliation behavior.
- Runtime truth must come from the approved reporting boundary.

## Game System rules
- Keep game definitions deterministic.
- Preserve game-definition schemas and action naming contracts unless explicitly updated.
- Prefer data-driven game metadata over product-wide game-specific forks.

## Agent rules
- Agent executes only.
- Agent must not invent lifecycle policy.
- Agent is the machine-local execution boundary.

## Determinism rules
- No hidden background behavior.
- No duplicate lifecycle control path outside Orchestrator.
- State transitions must remain explicit and request-driven.

## Legacy archive rules
- `legacy_desktop_archive/` is historical and quarantined.
- Do not expand legacy desktop code unless explicitly requested.
- Do not treat archived contracts as authoritative.

## Testing
Before finishing:

1. Run focused tests for the changed area when practical.
2. Run the full relevant suite if practical.

If a command cannot run, say so plainly.

## Output format
Always report:
- brief summary
- changed files
- exact verification commands run
- exact results

## Project-specific preferences
- Dummy-proof directions.
- For Codex tasks, use repo inspection and patch-style edits.
- Keep dormant code paths in place when asked to hide a feature.
- Default GameServers root for local testing on the user's machine:

`E:\GameServers\`

## Contract references
Follow these as authoritative:

- `new_contracts/00_REPO_ARCHITECTURE_OVERVIEW_v2.md`
- `new_contracts/IMPLEMENTATION_GAME_PLAN_v1.md`
- `new_contracts/AGENT_EXECUTION_RULES_v1.md`
- `new_contracts/PHASE_GATING_RULES_v1.md`
- `new_contracts/governance/CORE_GOVERNANCE_STANDARD_v2.md`
- `new_contracts/orchestrator/ORCHESTRATOR_LIFECYCLE_CONTRACT_v2.md`
- `new_contracts/backend/BACKEND_PUBLIC_API_CONTRACT_v1.md`
- `new_contracts/game_system/GAME_DEFINITION_SCHEMA_CONTRACT_v1.md`
- `new_contracts/shared/HOST_LOCAL_SETTINGS_OWNERSHIP_CONTRACT_v1.md`
- `new_contracts/shared/HOST_STORAGE_LAYOUT_CONTRACT_v1.md`
- `new_contracts/shared/SHARED_MASTER_INSTALL_CONTRACT_v1.md`
