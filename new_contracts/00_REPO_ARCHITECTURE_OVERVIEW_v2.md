# Repo Architecture Overview v2

Status: AUTHORITATIVE

Purpose: Defines the canonical section-based architecture for the project as it transitions from a desktop application to a cloud-based control plane.

## 1) Canonical End-To-End Architecture

```text
Frontend
  -> Backend API
  -> Orchestrator
  -> Game System
  -> Host Agent
  -> Game Runtime
```

Rules:

- Frontend is presentation plus action dispatch only.
- Backend API is the stable facade for frontend and any future external clients.
- Orchestrator owns lifecycle legality and canonical lifecycle state transitions.
- Game System owns supported-game definitions and game-specific data schemas.
- Host Agent executes machine-local work on the server host.
- Game Runtime is the managed process and related runtime artifacts for a specific server instance.

## 2) Section Mapping

- `ncc-frontend/`
  - browser UI, routing, session-aware views, dashboard, install flows
- `ncc-backend/`
  - public API, auth, orchestration routing, snapshot composition, event delivery
- `core/`
  - orchestration, lifecycle state management, coordination rules, shared server-control logic
- `ncc-agent/`
  - host-local execution of install, update, launch, stop, runtime inspection, and reporting
- `plugins/` legacy
  - historical implementation area only
- `game_system/` contract area
  - target architectural replacement for legacy plugin terminology and ownership

## 3) Ownership Model

### 3.1 Frontend ownership

- route and render views
- collect user input
- dispatch user intent to backend
- adapt snapshots for presentation
- display logs, events, and progress

### 3.2 Backend ownership

- stable API facade
- auth and access control
- input validation at API boundary
- route lifecycle intents to Orchestrator
- route non-lifecycle game actions through approved backend/game-system/agent boundaries
- compose snapshots
- deliver events to clients

### 3.3 Orchestrator ownership

- lifecycle legality
- lifecycle state transitions
- stop/restart reconciliation
- crash/restart policy integration
- coordination of install/update/lifecycle flows where lifecycle state is affected

### 3.4 Game System ownership

- supported game catalog
- game definition schema
- game-specific install, launch, config, RCON, and runtime metadata
- game reference profiles, including ARK: Survival Ascended

### 3.5 Host Agent ownership

- host-local execution
- process spawn/stop
- runtime inspection and reporting
- local filesystem interaction
- machine-local dependency and install work delegated by backend/orchestrator

## 4) Permanent Invariants

- Orchestrator remains lifecycle authority.
- Frontend must never own lifecycle legality.
- Backend must never take lifecycle authority away from Orchestrator.
- Host Agent must never invent alternate lifecycle policy.
- Game System must not own lifecycle legality.
- Shared contracts must define stable payloads for snapshots, events, actions, persistence, and errors.
- New games should be added through Game System definitions where practical, not through product-wide architectural forks.

## 5) Terminology

- `frontend` replaces `GUI` as the canonical client term.
- `backend API` replaces the old in-process `AdminAPI` as the canonical facade concept.
- `game_system` replaces `plugin` as the canonical architecture term for supported-game definition ownership.
- `host agent` is the machine-local execution surface.

## 6) ARK Position

- ARK: Survival Ascended is the first-class reference game for the current cloud direction.
- The product must still be shaped so that additional Steam-based games can be added later.
- The user-facing onboarding flow should be "select a supported game", not "install a plugin".

## 7) Legacy Contract Status

Legacy files under `contracts/` are historical references only.

Authoritative rules now live in `new_contracts/`.
