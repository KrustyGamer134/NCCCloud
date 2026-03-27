# Supported Game Catalog Contract v1

Status: AUTHORITATIVE

Purpose: Defines the supported-game catalog consumed by frontend and backend.

## 1) Rules

- backend exposes the supported-game catalog
- frontend presents the catalog to users during onboarding and provisioning
- each catalog entry must identify a stable game-system id
- display labels may vary, but stable ids must not drift without versioned contract change

## 2) Current Product Rule

- ARK: Survival Ascended is the primary supported game
- the catalog design must still support future Steam-based games without frontend architectural change
