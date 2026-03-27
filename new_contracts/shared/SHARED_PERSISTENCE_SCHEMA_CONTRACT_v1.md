# Shared Persistence Schema Contract v1

Status: AUTHORITATIVE

Purpose: Defines persistence expectations shared across backend, orchestrator, game system, and agent interactions.

## 1) Rules

- Persisted state must be explicit and versioned where schema exists.
- Persistence shapes must distinguish durable state from transient UI state.
- Game definition data, instance configuration, runtime metadata, and lifecycle metadata must remain distinguishable concerns.

## 2) Categories

- game definition records
- per-instance configuration
- lifecycle metadata
- install/update metadata
- agent-local runtime metadata

## 3) Compatibility

- Unknown persisted fields should be handled conservatively according to owning schema rules.
- Breaking persistence changes require a versioned contract update.
