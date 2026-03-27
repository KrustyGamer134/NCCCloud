# Backend Snapshot Composition Contract v1

Status: AUTHORITATIVE

Purpose: Defines backend composition of dashboard and detail views.

## 1) Rules

- backend may aggregate data from Orchestrator, Game System, and Agent sources
- composition must preserve authoritative field meanings
- backend must not mutate state as a side effect of read composition

## 2) Grouping Rules

- game-level grouping should follow supported game identifiers
- instance ordering should be deterministic within each grouped snapshot
