# Orchestrator Lifecycle Contract v2

Status: AUTHORITATIVE

Purpose: Defines the lifecycle-owned surface and state machine for managed instances.

## 1) Canonical Lifecycle-Owned Operations

- `start_instance`
- `stop_instance`
- `restart_instance`
- `disable_instance`
- `reenable_instance`
- `reconcile_stop_progress`

## 2) Canonical Lifecycle States

- `STOPPED`
- `STARTING`
- `RUNNING`
- `STOPPING`
- `RESTARTING`
- `UPDATING`
- `DISABLED`

Rules:

- Orchestrator alone may mutate these lifecycle states.
- Frontend and backend may present or route these states, but not redefine them.

## 3) Start Ownership

Current canonical rules:

- refuse when state is `DISABLED`
- refuse when state is not `STOPPED`
- refuse when install status is not `INSTALLED`
- record last action as `start`
- set state to `STARTING`
- invoke approved runtime start execution path
- if runtime truth confirms running, set state to `RUNNING`
- otherwise remain `STARTING` or return controlled failure as applicable

## 4) Stop Ownership

Current canonical rules:

- refuse when state is `DISABLED`
- gate on runtime truth first
- if not running, return controlled refusal
- if running, set last action to `stop`
- set state to `STOPPING`
- set stop deadline or equivalent reconciliation marker
- invoke graceful stop execution path
- call reconciliation path until runtime is confirmed stopped

## 5) Restart Ownership

Current canonical rules:

- refuse when crash restarts are paused and restart reason is crash-triggered
- refuse when state is `DISABLED`
- for manual restart, gate on runtime truth first
- set last action to `restart`
- set state to `RESTARTING`
- invoke graceful stop path
- perform runtime-aware restart sequencing
- invoke start path
- on success, record restart metadata and return to `RUNNING` when runtime truth confirms it

## 6) Disable And Reenable

### Disable

- ensure instance exists
- set state to `DISABLED`
- no game-runtime execution required

### Reenable

- ensure instance exists
- reset paused/disabled counters as contract requires
- set state to `STOPPED`
- no auto-start

## 7) Runtime-Truth Boundary

- Orchestrator must use the approved runtime reporting boundary
- runtime truth must not be replaced by ad hoc client assumptions
- runtime truth may inform legality, but does not transfer state ownership away from Orchestrator
