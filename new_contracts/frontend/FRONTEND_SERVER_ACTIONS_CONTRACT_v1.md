# Frontend Server Actions Contract v1

Status: AUTHORITATIVE

Purpose: Defines how frontend triggers server-related operations.

## 1) Canonical Action Set

- `start`
- `stop`
- `restart`
- `update`
- `provision`
- approved non-lifecycle actions

## 2) Rules

- frontend action controls dispatch intent only
- lifecycle legality remains backend/orchestrator-owned
- frontend may disable or enable controls based on snapshot state for UX
- frontend display logic must not become the source of truth for action legality

## 3) Transient State

Frontend may show temporary states such as:

- starting
- stopping
- provisioning
- updating

These are display-only until reconciled with backend snapshots.
