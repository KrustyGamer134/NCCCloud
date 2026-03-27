# Frontend Section Contract v1

Status: AUTHORITATIVE

Scope: `ncc-frontend/`

Purpose: Defines browser-client ownership and restrictions.

## 1) Frontend Ownership

- render product views
- present supported games and instances
- collect user input
- dispatch user intent to backend API
- render logs, events, and progress surfaces
- hold transient display-only state needed for UX

## 2) Frontend Non-Ownership

- lifecycle legality
- host execution
- game runtime inspection
- game definition authority
- persistence authority

## 3) Required Frontend Discipline

- frontend calls backend API only
- frontend must not call Orchestrator or agent code directly
- frontend must not assume local filesystem access
- frontend may normalize values for presentation only
- frontend must reconcile transient action state back to backend snapshots

## 4) Required UI Domains

- auth/session shell
- game selection
- dashboard or inventory view
- server detail
- logs/events
- settings/admin

## 5) Relationship To Other Contracts

- `FRONTEND_BACKEND_API_USAGE_CONTRACT_v1.md`
- `FRONTEND_ROUTING_AND_VIEW_OWNERSHIP_CONTRACT_v1.md`
- `FRONTEND_GAME_SELECTION_AND_INSTALL_FLOW_CONTRACT_v1.md`
- `FRONTEND_SERVER_ACTIONS_CONTRACT_v1.md`
- `FRONTEND_SNAPSHOT_RENDERING_CONTRACT_v1.md`
- `FRONTEND_LOGS_AND_EVENTS_VIEW_CONTRACT_v1.md`
