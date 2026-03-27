# Host Agent Runtime Execution Contract v1

Status: AUTHORITATIVE

Purpose: Defines host-local runtime execution and reporting.

## 1) Allowed Runtime Responsibilities

- launch a game server process using approved game metadata
- perform graceful stop or hard stop execution when instructed
- inspect runtime state using approved machine-local techniques
- report runtime-running and runtime-ready data upward

## 2) Rules

- agent executes runtime work delegated through approved backend/orchestrator pathways
- agent does not decide whether a runtime action is legal
- agent reports machine-readable runtime results

## 3) Runtime Truth Rule

Runtime truth used by Orchestrator must come from the approved reporting boundary. Agent-reported truth informs Orchestrator, but Orchestrator still owns lifecycle state transitions.
