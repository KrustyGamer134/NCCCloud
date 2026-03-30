# Host Local Settings Ownership Contract v1

Status: AUTHORITATIVE

Purpose: Defines which settings are authoritative on the cloud side versus the host side.

## 1) Canonical Ownership Split

### 1.1 Cloud-owned settings

These remain authoritative in the hosted control plane and must not be writable as host-local operational state:

- auth, identity, tenant, and session records
- plan, entitlement, and access-control state
- backend service configuration
- agent registration and cloud routing metadata
- other multi-tenant or security-sensitive product settings

### 1.2 Host-owned settings

These are authoritative on the user machine and must be read and written through the host execution boundary:

- gameserver root paths
- SteamCMD root paths
- machine-local cluster settings
- per-game or per-plugin host defaults
- per-instance operational configuration
- local install, master-install, cache, and runtime metadata

## 2) Routing Rules

- Frontend must submit settings intent through Backend API.
- Backend API may authorize and relay host-owned settings work, but must not become the durable authority for host-owned operational settings.
- Host-owned settings reads and writes must route through the approved host execution boundary.
- Cloud-owned settings must not be copied into host-local authority files unless explicitly required as a derived cache.

## 3) Visibility Rules

- Users must not receive direct access to cloud-only settings.
- Host-local settings are scoped to the machine that executes the game-host workload.
- Hosted settings reads must not source host-local settings from an unspecified or arbitrary machine.
- Hosted tenant-level settings reads must not expose host-owned values from a cloud-side fallback when no machine has been explicitly selected.
- Hosted plugin-default reads must not expose tenant-mirrored host defaults unless a specific host has been explicitly selected.
- Hosted multi-tenant storage must not silently override host-local operational settings once host-local authority is established.

## 4) Compatibility Rules

- Migration from cloud-stored operational settings to host-local authority must preserve stable frontend and backend request shapes where practical.
- Any remaining cloud-side mirrors or caches of host-owned settings must be clearly non-authoritative.
