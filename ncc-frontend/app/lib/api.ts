const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.krustystudios.com";

export interface InstanceDetailResponse {
  instance: {
    instance_id: string;
    display_name: string;
    plugin_id: string;
    game_system_id: string;
    status: string;
    install_status: string;
    agent_online: boolean;
    config_json: Record<string, unknown>;
  };
  status: {
    status: string;
    data?: {
      state?: string;
      install_status?: string;
      runtime_running?: boolean;
      runtime_ready?: boolean;
      [key: string]: unknown;
    };
  } | null;
  install_progress: {
    status: string;
    data?: {
      state?: string;
      install_log_tail?: string[];
      steamcmd_log_tail?: string[];
      progress_metadata?: Record<string, unknown> | null;
      [key: string]: unknown;
    };
  } | null;
  config_apply: {
    status: string;
    data?: {
      requires_restart?: boolean;
      pending_fields?: string[];
      [key: string]: unknown;
    };
  } | null;
  logs: {
    install_server?: {
      status: string;
      data?: { lines?: string[]; [key: string]: unknown };
    } | null;
    steamcmd_install?: {
      status: string;
      data?: { lines?: string[]; [key: string]: unknown };
    } | null;
    server?: {
      status: string;
      data?: { lines?: string[]; [key: string]: unknown };
    } | null;
  };
}

export interface PluginProvisioningMap {
  id: string;
  display_name: string;
}

export interface PluginProvisioningMetadata {
  default_map?: string;
  maps?: PluginProvisioningMap[];
}

export interface PluginSummary {
  plugin_id: string;
  game_system_id: string;
  display_name: string;
  description?: string | null;
  available_in_plans?: string[];
  provisioning?: PluginProvisioningMetadata | null;
}

export interface InstanceConfigSaveResponse {
  instance_id: string;
  config_json: Record<string, unknown>;
  apply_result?: {
    status?: string;
    message?: string;
    data?: {
      applied?: boolean;
      deferred?: boolean;
      requires_restart?: boolean;
      reason?: string;
      updated_fields?: string[];
      warnings?: string[];
    };
  } | null;
}

export async function fetchPlugins(token: string): Promise<PluginSummary[]> {
  const res = await fetch(`${API_URL}/plugins`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch plugins");
  return res.json();
}

export async function fetchAppSettings(token: string) {
  const res = await fetch(`${API_URL}/settings/app`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch app settings");
  return res.json();
}

export async function saveAppSettings(token: string, settings_json: Record<string, unknown>) {
  const res = await fetch(`${API_URL}/settings/app`, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ settings_json }),
  });
  if (!res.ok) throw new Error("Failed to save app settings");
  return res.json();
}

export async function fetchPluginSettings(token: string, pluginName: string) {
  const res = await fetch(`${API_URL}/settings/plugins/${encodeURIComponent(pluginName)}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Failed to fetch settings for plugin ${pluginName}`);
  return res.json();
}

export async function savePluginSettings(
  token: string,
  pluginName: string,
  plugin_json: Record<string, unknown>,
) {
  const res = await fetch(`${API_URL}/settings/plugins/${encodeURIComponent(pluginName)}`, {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ plugin_json }),
  });
  if (!res.ok) throw new Error(`Failed to save settings for plugin ${pluginName}`);
  return res.json();
}

export async function saveInstanceConfig(
  token: string,
  instanceId: string,
  config_json: Record<string, unknown>,
): Promise<InstanceConfigSaveResponse> {
  const res = await fetch(
    `${API_URL}/settings/instances/${encodeURIComponent(instanceId)}`,
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ config_json }),
    },
  );
  if (!res.ok) throw new Error(`Failed to save config for instance ${instanceId}`);
  return res.json();
}

export async function createInstance(
  token: string,
  body: {
    plugin_id: string;
    display_name: string;
    agent_id?: string;
    config_json?: Record<string, unknown>;
  },
) {
  const res = await fetch(`${API_URL}/instances`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail?.error ?? `Failed to create instance (${res.status})`);
  }
  return res.json();
}

export async function deleteInstance(token: string, instanceId: string) {
  const res = await fetch(`${API_URL}/instances/${encodeURIComponent(instanceId)}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail?.error ?? `Failed to delete instance (${res.status})`);
  }
}

export async function discoverInstances(token: string, agentId?: string) {
  const res = await fetch(`${API_URL}/instances/discover`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(agentId ? { agent_id: agentId } : {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail?.error ?? `Discover failed (${res.status})`);
  }
  return res.json();
}

export async function fetchAgents(token: string) {
  const res = await fetch(`${API_URL}/agents`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  console.log("AGENTS STATUS:", res.status);

  const text = await res.text();
  console.log("AGENTS RESPONSE:", text);

  if (!res.ok) throw new Error("Failed to fetch agents");

  return JSON.parse(text);
}

export async function fetchInstances(token: string) {
  const res = await fetch(`${API_URL}/instances`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  console.log("INSTANCES STATUS:", res.status);

  const text = await res.text();
  console.log("INSTANCES RESPONSE:", text);

  if (!res.ok) throw new Error("Failed to fetch instances");

  return JSON.parse(text);
}

export async function fetchInstanceDetail(token: string, instanceId: string): Promise<InstanceDetailResponse> {
  const res = await fetch(`${API_URL}/instances/${encodeURIComponent(instanceId)}/detail`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail?.error ?? `Failed to fetch instance detail (${res.status})`);
  }

  return res.json();
}

export async function runInstanceAction(
  token: string,
  instanceId: string,
  action: "install-server" | "start" | "stop" | "restart",
) {
  const res = await fetch(`${API_URL}/instances/${encodeURIComponent(instanceId)}/${action}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.detail?.error ?? `Failed to ${action} (${res.status})`);
  }

  return res.json();
}
