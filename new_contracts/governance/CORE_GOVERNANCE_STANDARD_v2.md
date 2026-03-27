# Core Governance Standard v2

Status: AUTHORITATIVE

Purpose: Defines the permanent architecture and change-discipline rules for the section-based cloud design.

## 1) Non-Negotiable Architecture Rules

- Orchestrator is the lifecycle authority.
- Backend API is the stable facade for frontend and external clients.
- Frontend routes all runtime and lifecycle work through backend API.
- Host Agent performs execution only through approved backend/orchestrator pathways.
- Game System provides supported-game definitions and game-specific metadata, not lifecycle authority.
- Runtime-truth ownership must be explicit and contract-defined.

## 2) Determinism Rules

- No hidden alternate lifecycle path may exist outside Orchestrator.
- No duplicate restart logic may exist across sections.
- State transitions must remain explicit and attributable to a request, event, or approved reconciliation path.
- Snapshot reads must not mutate state.
- Error paths must be controlled and machine-readable.

## 3) Section Boundary Rules

- Frontend may present and adapt data, but not enforce lifecycle legality.
- Backend may validate and authorize, but not redefine lifecycle semantics.
- Orchestrator may coordinate, but not collapse section boundaries into one monolith.
- Host Agent may execute and report, but not decide policy.
- Game System may define schemas, commands, and metadata, but not decide product-level policy.

## 4) Extensibility Rules

- Additional Steam-based games must fit through Game System contracts unless a new architecture contract is approved.
- ARK-specific exceptions are allowed only when documented and minimized.
- Additive capabilities must not silently break existing payloads or state meaning.

## 5) Test Discipline

- Contract-affecting changes require tests or schema validation updates in the same change group.
- Lifecycle changes must be backed by orchestrator-focused coverage.
- Snapshot and event schema changes must be backed by consumer compatibility checks where practical.

## 6) Legacy Status

- Old desktop-era contracts remain historical only.
- No new implementation work should cite legacy contracts as the authoritative source.
