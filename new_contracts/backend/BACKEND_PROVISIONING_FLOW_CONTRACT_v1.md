# Backend Provisioning Flow Contract v1

Status: AUTHORITATIVE

Purpose: Defines the canonical backend-coordinated provisioning and install flow.

## 1) Canonical Flow

1. resolve supported game
2. validate incoming configuration
3. allocate or create instance identity and required metadata
4. coordinate dependency, install, and game-specific setup work
5. update lifecycle-visible install state
6. return progress and resulting snapshots

## 2) Rules

- frontend must not orchestrate these steps itself
- provisioning may call agent and game-system-aware logic through approved routes
- lifecycle-visible state changes must remain consistent with Orchestrator ownership

## 3) ARK Reference Rule

ARK provisioning is the reference implementation for the initial cloud rollout.
