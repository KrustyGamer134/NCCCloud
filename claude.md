# CLAUDE.md

## Core Behavior Rules

- Never assume repository contents. Read the code first.
- Do not guess. Find the correct layer and the correct path.
- Prefer one correct fix over multiple speculative options.

## Code Modification Rules

- Always edit in place.
- Prefer minimal localized changes.
- Do not rewrite whole files unless necessary.
- Preserve structure and naming unless the task requires change.

## Active Architecture

System flow:

Frontend -> Backend API -> Orchestrator -> Game System -> Host Agent -> Game Runtime

## Responsibilities

### Frontend

- renders views
- collects user intent
- talks to backend API only

### Backend

- hosted API surface
- auth and validation
- snapshot composition
- routes lifecycle intent to Orchestrator

### Orchestrator

- lifecycle authority
- state transitions
- reconciliation

### Game System

- game-specific metadata and schemas
- ARK is the current reference game

### Host Agent

- machine-local execution
- process start/stop/install/update
- runtime inspection and reporting

## Strict Boundaries

- Frontend must not own lifecycle legality.
- Backend must not take lifecycle authority from Orchestrator.
- Agent must not invent lifecycle policy.
- Game System must not own lifecycle policy.
- Legacy archive is not the active product path.

## Contract Authority

Use `new_contracts/` as the source of truth.

Read first:

- `new_contracts/IMPLEMENTATION_GAME_PLAN_v1.md`
- `new_contracts/AGENT_EXECUTION_RULES_v1.md`
- `new_contracts/PHASE_GATING_RULES_v1.md`
- `new_contracts/governance/CORE_GOVERNANCE_STANDARD_v2.md`

## Validation Rules

Run the smallest relevant scope first.

Examples:

```bash
python -m pytest -q tests
```

```bash
cd ncc-backend
pytest
```

```bash
cd ncc-agent
pytest
```

## Legacy Rule

`legacy_desktop_archive/` is historical only unless the task explicitly targets it.

Do not expand or restore the old desktop architecture by accident.

## Task Execution Pattern

When given a task:

1. Identify the correct active layer.
2. Verify against `new_contracts/`.
3. Prefer the earliest incomplete phase from the implementation plan.
4. Apply the smallest safe fix.
5. Validate with the relevant tests.

## What Not To Do

- Do not build backwards.
- Do not prioritize discovery before install/start/stop is reliable.
- Do not build multi-game abstractions before ARK works end to end.
- Do not move logic across layers without clear contract support.
