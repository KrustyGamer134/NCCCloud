# Shared Master Install Contract v1

Status: AUTHORITATIVE

Purpose: Defines shared master installs used as the local source of truth for per-game install and update workflows.

## 1) Canonical Unit

A shared master install is:

- per host
- per supported game or game-system type
- shared across all compatible clusters and instances for that game on the same host

A shared master install is not:

- per tenant in cloud storage
- per instance
- per cluster when the underlying game payload is compatible

## 2) Canonical Responsibilities

- prepare or update a trusted local game payload once
- provide the reference payload for local distribution into instance installs
- provide the reference build/version target for update comparison

## 3) Storage Rules

- Shared masters must live under the host hidden control root defined by the host storage layout contract.
- Each supported game must resolve to a deterministic master path on that host.
- Multiple clusters using the same compatible game payload on the same host must reuse the same master.

## 4) Coordination Rules

- Backend and Frontend may request master preparation or update checks through approved routes.
- Orchestrator remains responsible for lifecycle-aware install/update coordination.
- Host Agent performs the machine-local preparation, validation, and distribution work.
- Game-specific install and validation logic remains game-system owned.

## 5) Compatibility Rules

- If a future supported game requires incompatible channels, branches, or payload variants, the master identity must expand to include a deterministic variant key by contract update.
- Until such a variant rule is introduced, one shared master per host per game-system type is canonical.
