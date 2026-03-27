# Backend Event Delivery Contract v1

Status: AUTHORITATIVE

Purpose: Defines backend ownership of event delivery to cloud clients.

## 1) Rules

- backend owns event delivery
- frontend does not own crash-watchdog or event-ingestion activation
- backend may expose polling, streaming, or subscription mechanisms
- event ingestion and policy routing remain backend/orchestrator-owned

## 2) Crash/Event Rule

- crash events may affect lifecycle policy only through Orchestrator
- frontend may observe resulting state and events, but does not own the policy path
