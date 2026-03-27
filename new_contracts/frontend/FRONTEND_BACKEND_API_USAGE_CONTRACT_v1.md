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
- frontend must not encode backend lifecycle rules
- frontend must not synthesize missing backend responses
