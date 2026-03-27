# Backend Public API Contract v1

Status: AUTHORITATIVE

Purpose: Defines the stable remote API boundary.

## 1) Required API Domains

- authentication/session
- supported game catalog
- dashboard and detail snapshots
- lifecycle actions
- provisioning/install/update actions
- logs and events
- settings/config metadata

## 2) Routing Rules

### 2.1 Lifecycle-intent routes

These must route to Orchestrator-owned lifecycle methods:

- start instance
- stop instance
- restart instance
- disable instance
- reenable instance

### 2.2 Non-lifecycle routes

These may route through approved backend/game-system/agent boundaries:

- validation
- install/update preparation
- non-lifecycle game actions
- log/event reads
- game catalog reads

## 3) Response Rules

- response payloads should align with shared contracts where applicable
- lifecycle refusal responses must preserve machine-readable error categories
- backend must not silently mask lifecycle authority outcomes
