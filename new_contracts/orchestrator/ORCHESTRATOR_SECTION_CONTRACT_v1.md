# Orchestrator Section Contract v1

Status: AUTHORITATIVE

Scope: Orchestration ownership in `core/`

Purpose: Defines Orchestrator as the canonical lifecycle authority.

## 1) Orchestrator Ownership

- lifecycle legality
- lifecycle transitions
- restart and stop reconciliation
- disabled-state enforcement
- crash/restart integration
- coordination with game-system and agent execution paths

## 2) Orchestrator Non-Ownership

- frontend presentation
- request authentication
- direct user-session concerns

## 3) Required Dependents

- backend must route lifecycle intents here
- agent must not bypass this layer
