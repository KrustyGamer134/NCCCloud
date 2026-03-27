# Shared Error Response Contract v1

Status: AUTHORITATIVE

Purpose: Defines common error categories and error-shape expectations across the system.

## 1) Canonical Shape

```json
{
  "status": "error",
  "data": {
    "category": "lifecycle_refused",
    "message": "Server is not running."
  }
}
```

## 2) Recommended Categories

- `validation_error`
- `authorization_error`
- `not_found`
- `lifecycle_refused`
- `execution_failed`
- `dependency_missing`
- `unsupported_action`

## 3) Rules

- Errors must be controlled and machine-readable.
- User-facing messaging may be friendlier, but the underlying category should remain available to callers.
- Unsupported actions must fail in a controlled way.
