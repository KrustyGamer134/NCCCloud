# Frontend Backend API Usage Contract v1

Status: AUTHORITATIVE

Purpose: Defines the allowed frontend-to-backend control surface.

## 1) Allowed Read Surface

Frontend may request:

- supported game catalog
- dashboard snapshots
- instance detail snapshots
- install/update status
- logs
- events
- settings/config metadata

## 2) Allowed Action Surface

Frontend may submit:

- start instance
- stop instance
- restart instance
- provision/install instance
- update instance
- non-lifecycle game-specific actions approved by backend

## 3) Rules

- frontend submits intent only
- backend is authoritative for routing and validation
- public frontend reads and writes must use the approved backend surface or same-origin proxy surface, not hardcoded cross-origin browser calls
- frontend must not encode backend lifecycle rules
- frontend must not synthesize missing backend responses
- frontend may edit cloud-owned or host-owned settings only through backend API
- frontend must not assume that backend DB storage is the authoritative persistence layer for host-owned operational settings
