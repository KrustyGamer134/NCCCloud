# Game System Section Contract v1

Status: AUTHORITATIVE

Purpose: Defines the target architecture replacing legacy plugin terminology and ownership.

## 1) Canonical Meaning

A Game System is the set of supported-game definitions, schemas, and game-specific execution metadata used by backend, Orchestrator, and agent components.

## 2) Ownership

- supported game catalog entries
- game definition schema
- install metadata
- launch metadata
- settings schema
- runtime reporting metadata
- RCON command metadata

## 3) Non-Ownership

- lifecycle legality
- frontend transport behavior
- backend auth and session rules

## 4) Design Rule

Where practical, supported-game behavior should be driven by data definitions rather than per-game product architecture forks.
