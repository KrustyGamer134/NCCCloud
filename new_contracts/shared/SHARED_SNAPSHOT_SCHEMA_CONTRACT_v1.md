# Shared Snapshot Schema Contract v1

Status: AUTHORITATIVE

Purpose: Defines the canonical rules for snapshot payloads returned across backend and orchestration read surfaces.

## 1) General Rules

- Snapshots are read-only state views.
- Snapshot reads must not mutate product state.
- Snapshot fields must be stable within a major version.
- Consumers must tolerate additive optional fields.
- Snapshot producers must not silently repurpose an existing field name.

## 2) Core Snapshot Types

### 2.1 Instance status snapshot

Canonical shape:

```json
{
  "game_system": "ark_survival_ascended",
  "instance_id": "island-1",
  "core_state": "RUNNING",
  "effective_state": "RUNNING",
  "last_action": "start",
  "runtime_running": true,
  "runtime_ready": true,
  "disabled": false,
  "install_status": "INSTALLED",
  "crash_total_count": 0,
  "crash_stability_count": 0,
  "effective_threshold": 3,
  "crash_restart_paused": false
}
```

Required fields:

- `game_system`
- `instance_id`
- `disabled`
- `crash_total_count`
- `crash_stability_count`
- `effective_threshold`
- `crash_restart_paused`

Optional fields:

- `core_state`
- `effective_state`
- `last_action`
- `runtime_running`
- `runtime_ready`
- `install_status`

Rules:

- `core_state` is the canonical lifecycle state owned by Orchestrator.
- `effective_state` may expose backend-normalized display state, but must not contradict `core_state`.
- `runtime_running` and `runtime_ready` represent runtime observations, not independent lifecycle authority.
- `install_status` is visibility-only and must not trigger installation side effects.

### 2.2 Dashboard snapshot

Canonical shape:

```json
{
  "games": {
    "ark_survival_ascended": {
      "instance_ids": ["island-1"],
      "status": [
        {
          "game_system": "ark_survival_ascended",
          "instance_id": "island-1",
          "install_status": "INSTALLED"
        }
      ],
      "error": null
    }
  }
}
```

Rules:

- Top-level grouping is by supported game identifier.
- `instance_ids` is the deterministic ordering for that game group.
- `status` entries are instance status snapshots or controlled per-instance error objects.
- `error` is a group-level read failure only.

### 2.3 Scheduler or maintenance snapshot

If exposed, maintenance/scheduler snapshots must clearly distinguish:

- maintenance activity
- pause state
- failed state
- current target scope
- next logical execution marker

Wall-clock assumptions must be explicit if used.

## 3) Enumerated Values

### 3.1 Core lifecycle states

- `STOPPED`
- `STARTING`
- `RUNNING`
- `STOPPING`
- `RESTARTING`
- `UPDATING`
- `DISABLED`

### 3.2 Install status values

- `NOT_INSTALLED`
- `INSTALLING`
- `INSTALLED`
- `FAILED`

## 4) Compatibility Rules

- Producers may add optional fields in minor versions.
- Consumers must not require unknown fields to be absent.
- Breaking shape changes require a major version bump.
