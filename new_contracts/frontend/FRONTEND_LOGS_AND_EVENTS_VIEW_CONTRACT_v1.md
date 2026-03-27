# Frontend Logs And Events View Contract v1

Status: AUTHORITATIVE

Purpose: Defines frontend rules for logs and events.

## 1) Allowed Behaviors

- show log streams or log pages supplied by backend
- show structured events supplied by backend
- search, filter, and paginate log/event content

## 2) Disallowed Behaviors

- no lifecycle legality from log parsing
- no hidden polling policy owned exclusively by the frontend
- no client-only event interpretation that changes authoritative state
