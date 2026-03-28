# Game Definition Schema Contract v1

Status: AUTHORITATIVE

Purpose: Defines the canonical data-driven schema for supported-game definitions.

## 1) General Rule

Game definitions should describe what the system needs to install, configure, launch, monitor, and interact with a game server.

## 2) Required Definition Domains

- schema version
- stable game-system id
- display name
- platform or distribution identifiers such as Steam app id where applicable
- executable path
- install layout metadata
- readiness and runtime metadata
- required ports
- settings schema
- config-file mapping metadata
- RCON metadata if supported

## 3) Example Shape

```json
{
  "schema_version": 1,
  "game_system": "ark_survival_ascended",
  "display_name": "ARK: Survival Ascended",
  "steam_app_id": "2430930",
  "executable": "ShooterGame\\Binaries\\Win64\\ArkAscendedServer.exe",
  "install_subfolder": "ArkSA",
  "ready_signal": "Server has completed startup and is now advertising for join.",
  "process_names": ["ArkAscendedServer.exe"],
  "required_ports": [
    {"name": "game", "proto": "udp"},
    {"name": "rcon", "proto": "tcp"}
  ],
  "rcon": {},
  "settings": {
    "shared": {},
    "instance": {}
  }
}
```

## 4) Rules

- schema changes require versioning
- unknown required-token or schema meaning changes require major-version handling
- game definitions must not encode product-level lifecycle policy
- for managed installs, the app-level game root is the filesystem base and any plugin-level install folder value must be treated as a relative folder name under that root, not as a replacement absolute path
- managed instance installs should resolve beneath the plugin folder root using deterministic map-based sequencing such as `<gameservers_root>/<plugin_folder>/<map>_<n>`
- plugin-owned metadata and instance config should resolve beneath `<gameservers_root>/<plugin_folder>/plugin/`
