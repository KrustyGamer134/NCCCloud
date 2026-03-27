"""
Shared Pydantic response models used across multiple route modules.

Keeping schemas in one place avoids duplicating from_orm_safe logic when
the same resource is returned by more than one endpoint.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from db.models import Instance


class InstanceResponse(BaseModel):
    """
    Full serialised representation of an Instance row.

    agent_online  - live flag: True when the assigned agent currently holds
                    an active WebSocket connection to this backend process.
                    This is an in-process, in-memory check; it is not persisted
                    and resets to False if the backend restarts.

    agent_last_seen - last timestamp at which the agent sent a status_update
                      that included this instance.  Persisted to the DB so it
                      survives backend restarts and agent disconnects.

    Transitional naming:
    - plugin_id remains for compatibility with the current DB/core model
    - game_system_id is the preferred hosted API field name
    """

    model_config = ConfigDict(from_attributes=True)

    instance_id: str
    tenant_id: str
    agent_id: str | None
    plugin_id: str
    game_system_id: str
    display_name: str
    config_json: dict
    status: str
    install_status: str
    agent_last_seen: str | None
    agent_online: bool
    created_at: str

    @classmethod
    def from_orm_safe(cls, inst: Instance) -> "InstanceResponse":
        # Late import avoids a module-level circular dependency:
        # schemas <- agents.is_agent_connected <- agent_ws._agent_connections
        from api.routes.agents import is_agent_connected

        agent_id_str = str(inst.agent_id) if inst.agent_id else None

        return cls(
            instance_id=str(inst.instance_id),
            tenant_id=str(inst.tenant_id),
            agent_id=agent_id_str,
            plugin_id=inst.plugin_id,
            game_system_id=inst.plugin_id,
            display_name=inst.display_name,
            config_json=inst.config_json or {},
            status=inst.status,
            install_status=inst.install_status,
            agent_last_seen=(
                inst.agent_last_seen.isoformat() if inst.agent_last_seen else None
            ),
            # If no agent is assigned, the instance is inherently "offline".
            agent_online=is_agent_connected(agent_id_str) if agent_id_str else False,
            created_at=inst.created_at.isoformat() if inst.created_at else "",
        )
