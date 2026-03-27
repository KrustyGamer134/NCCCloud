# Phase Gating Rules v1

Status: AUTHORITATIVE

Purpose: Prevents work from jumping ahead of the current project maturity.

## 1) Phase Order

Work must follow this order:

1. contracts and architecture
2. host execution foundation
3. Orchestrator lifecycle control
4. ARK end-to-end vertical slice
5. backend API stabilization
6. frontend workflow
7. discovery/import
8. additional Steam games

## 2) Gate Rule

Do not start the next phase if the current phase is not operationally complete.

## 3) Discovery Gate

Do not prioritize discovery or import work until:

- install works
- start works
- stop works
- restart works
- runtime status works

## 4) Multi-Game Gate

Do not prioritize additional game support until ARK works end to end through the cloud control path.

## 5) Frontend Gate

Do not rely on frontend logic to compensate for missing backend, Orchestrator, or agent behavior.

## 6) Exception Rule

A task may violate phase order only if there is a clear blocking reason and that reason is documented in the task itself.
