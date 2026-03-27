# Frontend Game Selection And Install Flow Contract v1

Status: AUTHORITATIVE

Purpose: Defines the frontend onboarding and provisioning UX for supported games.

## 1) Canonical User Flow

1. User views supported game catalog.
2. User selects a supported game.
3. Frontend loads game-specific templates, fields, and constraints from backend.
4. User submits provisioning configuration.
5. Frontend displays progress and resulting instance state from backend snapshots and events.

## 2) Rules

- User experience must be framed around supported games, not plugins.
- ARK: Survival Ascended is the first reference game.
- Additional Steam games must fit this same onboarding pattern.
- Frontend must not hardcode per-game execution logic when backend-provided metadata can drive the flow.
