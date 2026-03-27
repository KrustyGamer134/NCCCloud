# Shared Action Envelope Contract v1

Status: AUTHORITATIVE

Purpose: Defines canonical action request and response shapes across backend, orchestrator, game system, and agent boundaries.

## 1) Request Rules

Every action request must identify:

- target scope
- action intent
- action payload

Example:

```json
{
  "target": {
    "game_system": "ark_survival_ascended",
    "instance_id": "island-1"
  },
  "action": "start",
  "data": {}
}
```

Rules:

- `action` must be deterministic and documented.
- `data` must be a JSON-serializable object.
- Target identity must be explicit where instance scope applies.

## 2) Response Rules

Canonical response shape:

```json
{
  "status": "success",
  "data": {}
}
```

or

```json
{
  "status": "error",
  "data": {
    "message": "Server is not running."
  }
}
```

Rules:

- `status` must be `success` or `error`.
- `data` must be JSON-serializable.
- Action response meaning must not silently imply lifecycle-state mutation ownership outside Orchestrator.

## 3) Lifecycle Intent Rule

- Frontend and backend submit lifecycle intent.
- Orchestrator decides lifecycle legality.
- Successful execution reporting does not transfer lifecycle authority to the caller.
