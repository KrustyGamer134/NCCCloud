# Host Agent Health And Status Reporting Contract v1

Status: AUTHORITATIVE

Purpose: Defines agent-originated health and status reporting.

## 1) Reporting Domains

- process-running state
- readiness or startup observations
- install/update progress
- machine-local error conditions relevant to execution

## 2) Rules

- reporting must be machine-readable
- reporting does not grant lifecycle authority to the agent
- backend may aggregate or relay this data, but must preserve meaning
