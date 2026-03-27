# Implementation Game Plan v1

Status: AUTHORITATIVE

Purpose: Defines the required execution order for migrating the project from the desktop-oriented system to the cloud-oriented architecture without building the product backwards.

This file is written for humans and coding agents. It defines what to build first, what depends on what, what "done" means at each phase, and how the sections of the system must communicate.

## 1) Core Problem This Plan Fixes

The project must not build downstream or surface-level features before the core control path is complete.

Examples of backward progress:

- discovery works but install does not
- dashboard exists but start/stop is unreliable
- import exists but lifecycle control is incomplete
- multi-game ideas expand before ARK works end to end

The product is not complete when it can find servers. The product is complete when it can reliably provision, start, stop, restart, observe, and manage them through the intended cloud control path.

## 2) Canonical Architecture

```text
Frontend
  -> Backend API
  -> Orchestrator
  -> Game System
  -> Host Agent
  -> Game Runtime
```

## 3) Section Responsibilities

### 3.1 Frontend

- renders views
- collects user intent
- calls backend API
- shows progress, logs, events, and state

Frontend must not:

- decide lifecycle legality
- execute host actions
- contain game-runtime logic

### 3.2 Backend API

- stable remote facade
- authentication and authorization
- request validation
- snapshot composition
- lifecycle intent routing to Orchestrator
- event delivery to frontend

Backend API must not:

- take lifecycle authority from Orchestrator
- hide agent or runtime execution failures behind fake success

### 3.3 Orchestrator

- lifecycle authority
- canonical state transitions
- restart and stop reconciliation
- install/update coordination where lifecycle state is affected

Orchestrator must not:

- become a frontend presenter
- delegate lifecycle legality to agent or frontend

### 3.4 Game System

- supported-game definitions
- ARK reference profile
- install metadata
- launch metadata
- config metadata
- runtime metadata

Game System must not:

- own lifecycle policy
- replace Orchestrator

### 3.5 Host Agent

- host-local execution
- install/update execution
- process start/stop execution
- runtime inspection
- logs and progress reporting

Host Agent must not:

- decide policy
- invent restart rules
- become the system of record for lifecycle state

## 4) Non-Negotiable Build Order

Build in this order:

1. Contracts and architecture map
2. Host execution foundation
3. Orchestrator lifecycle control
4. ARK end-to-end vertical slice
5. Backend API stabilization
6. Frontend workflow
7. Discovery/import
8. Additional Steam games

If work is proposed out of order, compare it against this file first.

## 5) Phase Plan

## Phase 1: Contracts And Architecture Map

### Goal

Make the target system unambiguous before implementation expands further.

### Required outputs

- `new_contracts/` is the authoritative contract set
- old `contracts/` are historical only
- ownership is clear across frontend, backend, orchestrator, game_system, agent, and shared

### Definition of done

- no critical system behavior still depends on the old contract set for explanation
- no one is unclear about who owns install, start, stop, restart, runtime truth, or discovery

### Why this phase comes first

Without this, the project drifts and features get built in the wrong layer.

## Phase 2: Host Execution Foundation

### Goal

Make the machine hosting the server capable of doing real work reliably.

### Build first

- agent command path from backend/orchestrator to host
- install execution
- start execution
- stop execution
- runtime status reporting
- progress and log reporting

### Required capabilities

- install an ARK server on a host
- start the ARK server
- stop the ARK server
- report whether it is running
- report install or startup progress

### Definition of done

From backend or a direct internal control path, the system can command the agent to install, start, stop, and inspect one ARK server and get deterministic results back.

### Why this phase comes before frontend polish

If the host cannot do the work, everything above it is fake progress.

## Phase 3: Orchestrator Lifecycle Control

### Goal

Put all lifecycle legality and state transitions in one place.

### Build

- canonical lifecycle states
- start legality
- stop legality
- restart legality
- disable/reenable behavior
- stop reconciliation
- restart reconciliation
- runtime-truth ingestion from the approved reporting boundary

### Definition of done

- Orchestrator is the only place deciding whether an instance may start, stop, or restart
- backend routes lifecycle intent only
- agent executes only
- frontend presents only

### Required warning

Do not proceed to broad feature work if start/stop/restart are still partly owned elsewhere.

## Phase 4: ARK End-To-End Vertical Slice

### Goal

Make one full game work end to end before generalizing.

### Scope

ARK: Survival Ascended only

### Required working flow

1. select ARK
2. create or register a managed instance
3. install ARK server
4. write or apply ARK configuration
5. start ARK server
6. stop ARK server
7. restart ARK server
8. read runtime status
9. read logs and progress

### Definition of done

Starting from blank state, one ARK server can be provisioned and managed successfully through the cloud control path.

### Why ARK comes before generic multi-game support

The first vertical slice proves the architecture. Generic support before that usually creates abstractions that do not survive real execution.

## Phase 5: Backend API Stabilization

### Goal

Expose a stable remote surface once the core control path works.

### Build

- supported game catalog endpoints
- provisioning endpoints
- lifecycle action endpoints
- dashboard/detail snapshot endpoints
- logs/events endpoints
- stable error shapes

### Definition of done

- frontend can remain thin
- backend endpoints are sufficient for the product flow
- frontend does not need hidden workarounds for missing backend semantics

## Phase 6: Frontend Workflow

### Goal

Build the cloud UI on top of a working backend and Orchestrator path.

### Build in this order

1. game selection
2. provisioning/install flow
3. instance detail
4. start/stop/restart controls
5. logs and progress
6. dashboard summary
7. advanced admin views

### Definition of done

The frontend can drive the full ARK lifecycle path without owning business logic that belongs to backend or Orchestrator.

### Rule

The UI should reveal truth from the backend, not compensate for missing control-plane behavior.

## Phase 7: Discovery And Import

### Goal

Support adoption of existing servers after the managed path is already reliable.

### Build

- host scan for existing installations
- import candidate reporting
- validation of import candidates
- conversion of imported instances into normal managed instances

### Definition of done

Discovery/import does not bypass install, runtime, or lifecycle contracts. Imported servers become normal managed servers under Orchestrator control.

### Why this comes later

Discovery is not the core product. Reliable control is the core product.

## Phase 8: Additional Steam Games

### Goal

Expand support beyond ARK only after the first full slice is solid.

### Build

- additional game definitions through `game_system`
- bounded game-specific metadata and execution differences
- no product-wide architectural fork for each new game

### Definition of done

Adding a new Steam game mostly means adding metadata and bounded execution support, not reworking the full system.

## 6) Required Communication Paths

## 6.1 Provision / Install flow

```text
Frontend -> Backend API: provision game server
Backend API -> Orchestrator: create/manage instance and begin install flow
Orchestrator -> Game System: resolve game metadata
Orchestrator / Backend -> Host Agent: execute install/config/setup
Host Agent -> Orchestrator / Backend: progress, result, runtime/install status
Backend API -> Frontend: snapshots, events, progress
```

## 6.2 Start flow

```text
Frontend -> Backend API: start instance
Backend API -> Orchestrator: start intent
Orchestrator: validate legality
Orchestrator -> Host Agent: execute start using game metadata
Host Agent -> Orchestrator: runtime result
Orchestrator: update lifecycle state
Backend API -> Frontend: updated snapshot
```

## 6.3 Stop flow

```text
Frontend -> Backend API: stop instance
Backend API -> Orchestrator: stop intent
Orchestrator: validate legality using runtime truth
Orchestrator -> Host Agent: graceful stop
Host Agent -> Orchestrator: stop result and runtime status
Orchestrator: reconcile until stopped
Backend API -> Frontend: updated snapshot
```

## 6.4 Restart flow

```text
Frontend -> Backend API: restart instance
Backend API -> Orchestrator: restart intent
Orchestrator: validate legality and restart rules
Orchestrator -> Host Agent: stop then start execution path
Host Agent -> Orchestrator: runtime results
Orchestrator: reconcile and update state
Backend API -> Frontend: updated snapshot
```

## 7) Things Agents Must Not Do

- Do not build discovery before install/start/stop are reliable unless explicitly ordered for a business reason.
- Do not put lifecycle legality into frontend.
- Do not put lifecycle legality into backend route handlers if Orchestrator should own it.
- Do not let agent invent restart or recovery policy.
- Do not build multi-game abstractions before the ARK vertical slice works end to end.
- Do not treat dashboards or server lists as proof the system works.

## 8) Immediate Project Objective

The immediate objective for the project is:

**Make ARK provisioning and lifecycle management work end to end through the cloud control path before expanding discovery or additional game support.**

## 9) Agent Working Rule

When choosing between tasks, prefer the task that most directly improves this sequence:

1. agent execution reliability
2. Orchestrator lifecycle correctness
3. ARK end-to-end manageability
4. backend API completeness
5. frontend usability
6. discovery/import
7. additional game support

If a task does not move one of those forward, it is probably not on the critical path.
