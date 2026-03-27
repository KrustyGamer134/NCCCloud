# Agent Execution Rules v1

Status: AUTHORITATIVE

Purpose: Short operational rules for humans and coding agents working in this repo.

## 1) Critical Path Rule

Always prefer the earliest incomplete phase from `IMPLEMENTATION_GAME_PLAN_v1.md`.

If a task does not move the earliest incomplete phase forward, it is probably not the right task.

## 2) Architecture Rule

- Frontend does not own lifecycle legality.
- Backend does not take lifecycle authority away from Orchestrator.
- Orchestrator owns lifecycle legality and state transitions.
- Host Agent executes only.
- Game System defines game-specific metadata and schemas only.

## 3) Build Order Rule

Do not build the system backwards.

Do not prioritize:

- discovery before install/start/stop
- dashboard polish before reliable control
- multi-game abstraction before ARK works end to end
- UI workarounds for missing backend behavior

## 4) ARK Rule

ARK: Survival Ascended is the reference vertical slice.

Until ARK provisioning and lifecycle management work end to end, broad expansion work is lower priority.

## 5) Implementation Rule

- Prefer the smallest safe change.
- Do not move logic into the wrong layer.
- Do not create duplicate control paths.
- Do not invent hidden background behavior.

## 6) When In Doubt

Choose the task that improves:

1. agent execution reliability
2. Orchestrator lifecycle correctness
3. ARK end-to-end manageability
4. backend API completeness
5. frontend usability
