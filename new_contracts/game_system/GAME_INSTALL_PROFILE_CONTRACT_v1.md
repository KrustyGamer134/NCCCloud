# Game Install Profile Contract v1

Status: AUTHORITATIVE

Purpose: Defines game-specific install and update metadata.

## 1) Required Domains

- distribution or package id
- executable path
- install subfolder or layout metadata
- dependency requirements
- launch template or equivalent launch metadata
- config-file mapping metadata

## 2) Rules

- install metadata belongs to the Game System
- execution of installs belongs to agent/runtime pathways
- backend and Orchestrator may coordinate install state, but do not redefine the underlying game profile metadata
