# Orchestrator Install Update Coordination Contract v1

Status: AUTHORITATIVE

Purpose: Defines lifecycle-aware coordination of install and update flows.

## 1) Canonical Rule

Install and update work may involve backend, game-system, and agent execution, but any lifecycle-visible state changes remain consistent with Orchestrator ownership.

## 2) Rules

- install/update flows must not bypass lifecycle state semantics
- update flows must not create hidden restart policy outside Orchestrator
- failures must surface as controlled execution or install-state failures

## 3) Deploy Sequence Reference

Where a deploy-style sequence is used, the canonical ordered model is:

1. validate
2. install dependencies or prepare runtime requirements
3. install server
4. start

Later expansions must update this contract explicitly.
