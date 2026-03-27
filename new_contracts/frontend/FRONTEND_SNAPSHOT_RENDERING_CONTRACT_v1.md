# Frontend Snapshot Rendering Contract v1

Status: AUTHORITATIVE

Purpose: Defines frontend consumption of backend snapshots.

## 1) Rules

- frontend may transform raw payloads into view models
- frontend must preserve backend meaning of lifecycle and install states
- frontend must tolerate additive optional fields
- frontend must not infer uncontracted semantics from unknown fields

## 2) Snapshot Sources

- dashboard snapshots
- instance detail snapshots
- maintenance or scheduler snapshots if exposed

## 3) Canonical Dependency

This contract depends on `shared/SHARED_SNAPSHOT_SCHEMA_CONTRACT_v1.md`.
