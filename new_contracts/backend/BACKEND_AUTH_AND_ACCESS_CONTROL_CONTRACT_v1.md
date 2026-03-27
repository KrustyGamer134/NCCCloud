# Backend Auth And Access Control Contract v1

Status: AUTHORITATIVE

Purpose: Defines backend ownership for authentication and authorization.

## 1) Rules

- backend authenticates callers before serving protected routes
- backend authorizes action categories before routing
- authorization must occur above Orchestrator lifecycle semantics

## 2) Non-Rules

- authorization must not create alternate lifecycle semantics
- authorization failure must not be reported as lifecycle refusal
