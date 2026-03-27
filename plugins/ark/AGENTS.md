# AGENTS.md

## Scope
Rules in this file apply to work under `plugins/ark/`.

## ARK plugin role
- Implement deterministic ARK-specific behavior behind the plugin action surface.
- Preserve the public plugin request surface in `plugins/ark/main.py`.
- Keep plugin behavior compatible with AdminAPI and Orchestrator contracts.
- Preserve compatibility wrappers if tests depend on them.

## ARK working rules
- Prefer minimal patch-style edits.
- Do not introduce async, background loops, sleeps, or race-prone behavior.
- Do not change action names, payload shapes, or response contracts unless explicitly requested.
- Keep `main.py` as the top-level plugin surface / dispatcher.
- Keep extracted modules focused by responsibility.

## Determinism rules
- No background orchestration.
- No polling loops.
- No implicit lifecycle transitions.
- Lifecycle actions must remain request-driven.

## Testing
Run focused ARK/plugin tests when practical, then run the full suite:

`python -m pytest -q`

Expected baseline:
`238 passed, 1 skipped`

## Contract references
Use these as authoritative when relevant:

- `contracts/Ark_Plugin_Action_Surface_Contract_v1.0.md`
- `contracts/Ark_Launch_Runtime_Contract_v1.0.md`
- `contracts/Ark_Plugin_Config_Contract_v1.0.md`
- `contracts/AdminAPI_Plugin_Action_Contract_v1.0.md`