# Orchestrator Restart And Reconciliation Contract v1

Status: AUTHORITATIVE

Purpose: Defines stop/restart reconciliation semantics.

## 1) Reconciliation Ownership

- reconciliation is Orchestrator-owned
- clients may trigger reads or observe results, but do not own the reconciliation algorithm

## 2) Stop Reconciliation Rules

- applies only when state is `STOPPING`
- if runtime is gone, set `STOPPED`
- if runtime remains and deadline has not expired, remain `STOPPING`
- if deadline expires, invoke hard-stop path and recheck runtime truth

## 3) Restart Reconciliation Rules

- restart sequencing remains Orchestrator-owned
- restart success depends on approved runtime truth after stop/start sequencing
- scheduled and manual restart semantics must remain explicit if both are supported
