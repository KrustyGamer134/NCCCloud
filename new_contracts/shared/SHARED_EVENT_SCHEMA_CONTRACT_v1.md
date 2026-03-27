# Shared Event Schema Contract v1

Status: AUTHORITATIVE

Purpose: Defines canonical rules for structured events delivered to backend and frontend consumers.

## 1) Event Rules

- Events must be structured objects, not free-form log lines.
- Events must identify event type and target scope.
- Events must be version-tolerant for consumers.

Example:

```json
{
  "type": "instance_crashed",
  "game_system": "ark_survival_ascended",
  "instance_id": "island-1",
  "data": {
    "reason": "process_exited"
  }
}
```

## 2) Ownership Rules

- Event ingestion and routing are backend/orchestrator responsibilities.
- Frontend may display events but must not derive policy from them directly.
- Event delivery must not create a duplicate lifecycle path outside Orchestrator.

## 3) Stability Rules

- Event type meanings must remain stable within a major version.
- New event types may be added additively.
