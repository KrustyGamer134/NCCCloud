# Host Storage Layout Contract v1

Status: AUTHORITATIVE

Purpose: Defines the host-local filesystem layout for visible server installs and hidden control-plane data.

## 1) Canonical Host Layout

Given a configured machine root such as `<host_root>`, the host-local layout should be separated into:

- a visible server install root for user-managed server instances
- a hidden control root for app-managed metadata, state, and shared install assets

## 2) Canonical Categories

### 2.1 Visible server install root

This contains user-visible server instance installs, for example:

- `<host_root>\servers\<instance_install>\...`

### 2.2 Hidden control root

This contains app-managed control-plane data, for example:

- `<host_root>\.ncc\config\...`
- `<host_root>\.ncc\state\...`
- `<host_root>\.ncc\cache\...`
- `<host_root>\.ncc\logs\...`
- `<host_root>\.ncc\masters\...`

The hidden control root name may change by approved contract update, but the separation of visible installs from hidden control data must remain explicit.

## 3) Rules

- Shared masters must live under the hidden control root, not inside a specific instance install.
- Host-local config and state files must not be scattered across instance install folders unless the owning workflow explicitly requires instance-scoped artifacts.
- User-facing instance installs should remain easy to browse without mixing in unrelated control-plane files.

## 4) Override Rules

- Specific paths may be configured by approved settings, but the ownership categories in this contract remain the same.
- Relative game-definition install folders must resolve beneath the visible server install root unless a contract-approved exception exists.
