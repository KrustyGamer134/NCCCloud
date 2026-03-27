# Host Agent Install And Update Execution Contract v1

Status: AUTHORITATIVE

Purpose: Defines host-side execution of dependency, install, and update work.

## 1) Allowed Responsibilities

- verify or install required host-local prerequisites
- perform game distribution install or update steps
- write approved config artifacts as part of install/setup workflows
- report progress and result state

## 2) Rules

- agent executes only requested work
- backend and Orchestrator own the larger flow and visible state semantics
- failures must be returned as controlled execution failures
