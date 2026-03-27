# Backend Section Contract v1

Status: AUTHORITATIVE

Scope: `ncc-backend/`

Purpose: Defines backend ownership as the stable remote facade for the cloud product.

## 1) Backend Ownership

- public API surface
- auth and access control enforcement
- request validation
- snapshot composition
- event delivery
- provisioning coordination
- routing lifecycle intent to Orchestrator

## 2) Backend Non-Ownership

- backend does not become lifecycle authority
- backend does not replace host execution with client-side assumptions
- backend does not redefine game metadata owned by Game System contracts

## 3) Primary Contract Dependencies

- `BACKEND_PUBLIC_API_CONTRACT_v1.md`
- `BACKEND_AUTH_AND_ACCESS_CONTROL_CONTRACT_v1.md`
- `BACKEND_PROVISIONING_FLOW_CONTRACT_v1.md`
- `BACKEND_EVENT_DELIVERY_CONTRACT_v1.md`
- `BACKEND_SNAPSHOT_COMPOSITION_CONTRACT_v1.md`
