"use client";

import { useAuth, UserButton } from "@clerk/nextjs";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  createInstance,
  deleteInstance,
  discoverInstances,
  fetchAgents,
  fetchPlugins,
  type PluginSummary,
} from "../lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.krustystudios.com";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface Instance {
  instance_id: string;
  display_name: string;
  plugin_id: string;
  status: string;
  agent_online: boolean;
}

interface Plugin {
  plugin_id: string;
  display_name: string;
  provisioning?: {
    default_map?: string;
    maps?: Array<{ id: string; display_name: string }>;
  } | null;
}

interface Agent {
  agent_id: string;
  machine_name: string;
  is_connected: boolean;
}

type Action = "start" | "stop" | "restart";

const EMPTY_FORM = { display_name: "", plugin_id: "", agent_id: "", map: "" };

// ─────────────────────────────────────────────────────────────────────────────
// Small display components
// ─────────────────────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  running: "bg-green-900 text-green-300 border border-green-700",
  stopped: "bg-gray-800 text-gray-400 border border-gray-700",
  starting: "bg-yellow-900 text-yellow-300 border border-yellow-700",
  stopping: "bg-yellow-900 text-yellow-300 border border-yellow-700",
  error: "bg-red-900 text-red-300 border border-red-700",
};

function StatusBadge({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.stopped;
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${style}`}>
      {status}
    </span>
  );
}

function AgentBadge({ online }: { online: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-xs font-medium ${
        online
          ? "bg-emerald-900 text-emerald-300 border border-emerald-700"
          : "bg-gray-800 text-gray-500 border border-gray-700"
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full ${online ? "bg-emerald-400" : "bg-gray-600"}`} />
      {online ? "Online" : "Offline"}
    </span>
  );
}

function TrashIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6M14 11v6" />
      <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    </svg>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

export default function InstancesPage() {
  const { getToken } = useAuth();
  const router = useRouter();

  const [instances, setInstances] = useState<Instance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, Action>>({});

  // Add Server modal
  const [showModal, setShowModal] = useState(false);
  const [modalPlugins, setModalPlugins] = useState<Plugin[]>([]);
  const [modalAgents, setModalAgents] = useState<Agent[]>([]);
  const [modalLoading, setModalLoading] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [addError, setAddError] = useState<string | null>(null);
  const [addBusy, setAddBusy] = useState(false);

  // Discover
  const [discovering, setDiscovering] = useState(false);
  const [discoverMsg, setDiscoverMsg] = useState<string | null>(null);

  // Discover results modal
  const [showDiscoverModal, setShowDiscoverModal] = useState(false);
  const [discoverServers, setDiscoverServers] = useState<Array<{ name: string; path: string }>>([]);
  const [selectedServers, setSelectedServers] = useState<Set<string>>(new Set());
  const [discoverPlugins, setDiscoverPlugins] = useState<Plugin[]>([]);
  const [discoverAgents, setDiscoverAgents] = useState<Agent[]>([]);
  const [discoverPluginId, setDiscoverPluginId] = useState("");
  const [discoverAgentId, setDiscoverAgentId] = useState("");
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  // Delete
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const selectedPlugin = modalPlugins.find((plugin) => plugin.plugin_id === form.plugin_id);
  const selectedPluginMaps = selectedPlugin?.provisioning?.maps ?? [];
  const managedCreateRequiresAgent = selectedPluginMaps.length > 0;
  const connectedModalAgents = modalAgents.filter((agent) => agent.is_connected);
  const createDisabled =
    addBusy ||
    modalLoading ||
    !form.display_name.trim() ||
    !form.plugin_id ||
    (selectedPluginMaps.length > 0 && !form.map) ||
    (managedCreateRequiresAgent && !form.agent_id);

  function buildInitialForm(plugs: PluginSummary[], agts: Agent[]) {
    const firstPlugin = plugs[0];
    const preferredAgent =
      agts.find((agent) => agent.is_connected)?.agent_id ?? agts[0]?.agent_id ?? "";
    return {
      ...EMPTY_FORM,
      plugin_id: firstPlugin?.plugin_id ?? "",
      agent_id: preferredAgent,
      map:
        firstPlugin?.provisioning?.default_map ??
        firstPlugin?.provisioning?.maps?.[0]?.id ??
        "",
    };
  }

  function handlePluginChange(pluginId: string) {
    const plugin = modalPlugins.find((item) => item.plugin_id === pluginId);
    const nextMap =
      plugin?.provisioning?.default_map ?? plugin?.provisioning?.maps?.[0]?.id ?? "";
    setForm((current) => ({
      ...current,
      display_name: current.display_name || nextMap,
      plugin_id: pluginId,
      map: nextMap,
    }));
  }

  // ── Fetch instances ────────────────────────────────────────────────────────
  const loadInstances = useCallback(async () => {
    try {
      const token = await getToken();
      const res = await fetch(`${API_URL}/instances`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`Failed to fetch instances (${res.status})`);
      setInstances(await res.json());
      setError(null);
    } catch (e: any) {
      setError(e.message ?? "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    loadInstances();
  }, [loadInstances]);

  // ── Start / Stop / Restart ─────────────────────────────────────────────────
  async function handleAction(instanceId: string, action: Action) {
    setPending((p) => ({ ...p, [instanceId]: action }));
    try {
      const token = await getToken();
      const res = await fetch(`${API_URL}/instances/${instanceId}/${action}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`${action} failed (${res.status})`);
    } catch (e: any) {
      setError(e.message ?? "Unknown error");
    } finally {
      setPending((p) => {
        const next = { ...p };
        delete next[instanceId];
        return next;
      });
      await loadInstances();
    }
  }

  // ── Delete ─────────────────────────────────────────────────────────────────
  async function handleDelete(instanceId: string) {
    if (!confirm("Delete this instance? This cannot be undone.")) return;
    setDeletingId(instanceId);
    try {
      const token = await getToken();
      await deleteInstance(token!, instanceId);
      await loadInstances();
    } catch (e: any) {
      setError(e.message ?? "Unknown error");
    } finally {
      setDeletingId(null);
    }
  }

  // ── Open Add modal ─────────────────────────────────────────────────────────
  async function openModal() {
    setForm(EMPTY_FORM);
    setAddError(null);
    setShowModal(true);
    setModalLoading(true);
    try {
      const token = await getToken();
      const [plugs, agts] = await Promise.all([
        fetchPlugins(token!),
        fetchAgents(token!),
      ]);
      setModalPlugins(plugs);
      setModalAgents(agts);
      // Pre-select first options
      setForm(buildInitialForm(plugs, agts));
    } catch (e: any) {
      setAddError(e.message ?? "Failed to load plugins/agents");
    } finally {
      setModalLoading(false);
    }
  }

  // ── Submit Add form ────────────────────────────────────────────────────────
  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!form.display_name.trim()) {
      setAddError("Name is required.");
      return;
    }
    if (!form.plugin_id) {
      setAddError("Please select a plugin.");
      return;
    }
    if (selectedPluginMaps.length > 0 && !form.map) {
      setAddError("Please select a map.");
      return;
    }
    if (managedCreateRequiresAgent && !form.agent_id) {
      setAddError("Please select a connected agent for managed provisioning.");
      return;
    }
    setAddBusy(true);
    setAddError(null);
    try {
      const token = await getToken();
      const created = await createInstance(token!, {
        display_name: form.display_name.trim(),
        plugin_id: form.plugin_id,
        agent_id: form.agent_id || undefined,
        config_json: form.map ? { map: form.map } : undefined,
      });
      setShowModal(false);
      setForm(EMPTY_FORM);
      router.push(`/instances/${encodeURIComponent(created.instance_id)}`);
    } catch (e: any) {
      setAddError(e.message ?? "Unknown error");
    } finally {
      setAddBusy(false);
    }
  }

  // ── Discover ───────────────────────────────────────────────────────────────
  async function handleDiscover() {
    setDiscovering(true);
    setDiscoverMsg(null);
    try {
      const token = await getToken();

      // Let the backend auto-select an agent — no need to fetch agents here.
      const raw = await discoverInstances(token!);

      // The relay may return the agent envelope directly
      // ({status, data: {servers:[]}}) or unwrapped ({servers:[]}).
      // Handle both.
      const servers: Array<{ name: string; path: string }> =
        Array.isArray(raw?.servers)
          ? raw.servers
          : Array.isArray(raw?.data?.servers)
          ? raw.data.servers
          : [];

      if (servers.length === 0) {
        setDiscoverMsg("No server folders found. Check gameservers_root in Settings.");
        return;
      }

      // Fetch plugins + agents for the import step
      const [plugs, agts] = await Promise.all([
        fetchPlugins(token!),
        fetchAgents(token!).catch(() => [] as Agent[]),
      ]);
      setDiscoverPlugins(plugs);
      setDiscoverAgents(agts);
      setDiscoverPluginId(plugs[0]?.plugin_id ?? "");
      setDiscoverAgentId(
        agts.find((a) => a.is_connected)?.agent_id ?? agts[0]?.agent_id ?? ""
      );

      setDiscoverServers(servers);
      // Pre-select everything
      setSelectedServers(new Set(servers.map((s) => s.name)));
      setImportError(null);
      setShowDiscoverModal(true);
    } catch (e: any) {
      setDiscoverMsg(`Error: ${e.message}`);
    } finally {
      setDiscovering(false);
    }
  }

  // ── Import selected discovered servers ─────────────────────────────────────
  async function handleImport() {
    if (selectedServers.size === 0) return;
    setImportBusy(true);
    setImportError(null);
    const token = await getToken();
    let created = 0;
    const errors: string[] = [];
    for (const server of discoverServers) {
      if (!selectedServers.has(server.name)) continue;
      try {
        await createInstance(token!, {
          display_name: server.name,
          plugin_id: discoverPluginId,
          agent_id: discoverAgentId || undefined,
        });
        created++;
      } catch (e: any) {
        errors.push(`${server.name}: ${e.message}`);
      }
    }
    setImportBusy(false);
    if (errors.length > 0) {
      setImportError(
        `Imported ${created}, failed ${errors.length}:\n${errors.join("\n")}`
      );
      // Don't close — let user see what failed
    } else {
      setShowDiscoverModal(false);
      setDiscoverMsg(`Imported ${created} server(s).`);
    }
    await loadInstances();
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Nav */}
      <nav className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-xl font-bold text-white hover:text-gray-300">
            NCC
          </Link>
          <span className="text-gray-500 text-sm">Game Server Manager</span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/" className="text-sm text-gray-400 hover:text-white transition-colors">
            Dashboard
          </Link>
          <span className="text-sm text-white font-medium">Game Servers</span>
          <Link href="/settings" className="text-sm text-gray-400 hover:text-white transition-colors">
            Settings
          </Link>
          <UserButton />
        </div>
      </nav>

      <main className="px-6 py-8">
        {/* Header row */}
        <div className="flex items-center justify-between mb-6 gap-3 flex-wrap">
          <h1 className="text-2xl font-bold">Game Servers</h1>
          <div className="flex items-center gap-2">
            {discoverMsg && (
              <span
                className={`text-xs ${
                  discoverMsg.startsWith("Error") ? "text-red-400" : "text-gray-400"
                }`}
              >
                {discoverMsg}
              </span>
            )}
            <button
              onClick={handleDiscover}
              disabled={discovering}
              className="text-sm text-gray-400 hover:text-white transition-colors px-3 py-1.5 rounded border border-gray-700 hover:border-gray-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {discovering ? "Discovering…" : "Discover Servers"}
            </button>
            <button
              onClick={openModal}
              className="text-sm bg-blue-700 hover:bg-blue-600 text-white px-3 py-1.5 rounded border border-blue-600 transition-colors"
            >
              + Add Server
            </button>
            <button
              onClick={loadInstances}
              className="text-sm text-gray-400 hover:text-white transition-colors px-3 py-1.5 rounded border border-gray-700 hover:border-gray-500"
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="mb-4 px-4 py-3 rounded bg-red-950 border border-red-800 text-red-300 text-sm">
            {error}
          </div>
        )}

        {/* Table */}
        {loading ? (
          <div className="text-gray-500 text-sm py-12 text-center">Loading…</div>
        ) : instances.length === 0 ? (
          <div className="py-12 text-center">
            <p className="text-sm text-gray-400">No managed servers yet.</p>
            <p className="mt-2 text-sm text-gray-500">
              Start with <span className="text-white">Add Server</span> for the ARK managed path.
              Use <span className="text-white">Discover Servers</span> later for import.
            </p>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-800 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-900 border-b border-gray-800">
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">Name</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">Plugin</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">Status</th>
                  <th className="text-left px-4 py-3 text-gray-400 font-medium">Agent</th>
                  <th className="text-right px-4 py-3 text-gray-400 font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {instances.map((inst, idx) => {
                  const busy = inst.instance_id in pending;
                  const busyAction = pending[inst.instance_id];
                  const isDeleting = deletingId === inst.instance_id;
                  const actionsDisabled = busy || isDeleting || !inst.agent_online;
                  return (
                    <tr
                      key={inst.instance_id}
                      className={`border-b border-gray-800 last:border-0 ${
                      idx % 2 === 0 ? "bg-gray-950" : "bg-gray-900/40"
                      }`}
                    >
                      <td className="px-4 py-3 font-medium">
                        <Link
                          href={`/instances/${encodeURIComponent(inst.instance_id)}`}
                          className="hover:text-blue-300 transition-colors"
                        >
                          {inst.display_name}
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-gray-400 font-mono text-xs">
                        {inst.plugin_id}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={inst.status} />
                      </td>
                      <td className="px-4 py-3">
                        <AgentBadge online={inst.agent_online} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <ActionButton
                            label="Start"
                            busy={busy && busyAction === "start"}
                            disabled={actionsDisabled}
                            onClick={() => handleAction(inst.instance_id, "start")}
                            variant="green"
                          />
                          <ActionButton
                            label="Stop"
                            busy={busy && busyAction === "stop"}
                            disabled={actionsDisabled}
                            onClick={() => handleAction(inst.instance_id, "stop")}
                            variant="red"
                          />
                          <ActionButton
                            label="Restart"
                            busy={busy && busyAction === "restart"}
                            disabled={actionsDisabled}
                            onClick={() => handleAction(inst.instance_id, "restart")}
                            variant="yellow"
                          />
                          {/* Delete */}
                          <button
                            onClick={() => handleDelete(inst.instance_id)}
                            disabled={busy || isDeleting}
                            title={inst.agent_online ? "Delete instance" : "Agent offline"}
                            className="p-1.5 rounded text-gray-500 hover:text-red-400 hover:bg-red-950 border border-transparent hover:border-red-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            {isDeleting ? "…" : <TrashIcon />}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </main>

      {/* ── Discover Results Modal ───────────────────────────────────────────── */}
      {showDiscoverModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={(e) => {
            if (e.target === e.currentTarget && !importBusy) setShowDiscoverModal(false);
          }}
        >
          <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-lg mx-4 flex flex-col max-h-[80vh]">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 shrink-0">
              <div>
                <h2 className="text-lg font-semibold">Discovered Servers</h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  {discoverServers.length} folder(s) found — select which to import
                </p>
              </div>
              <button
                onClick={() => setShowDiscoverModal(false)}
                disabled={importBusy}
                className="text-gray-500 hover:text-white text-xl leading-none disabled:opacity-40"
              >
                ×
              </button>
            </div>

            {/* Server list */}
            <div className="overflow-y-auto flex-1 px-6 py-3 space-y-1">
              {/* Select all toggle */}
              <label className="flex items-center gap-2 py-1 text-xs text-gray-500 cursor-pointer hover:text-gray-300 select-none">
                <input
                  type="checkbox"
                  className="accent-blue-500"
                  checked={selectedServers.size === discoverServers.length}
                  onChange={(e) => {
                    setSelectedServers(
                      e.target.checked
                        ? new Set(discoverServers.map((s) => s.name))
                        : new Set()
                    );
                  }}
                />
                Select all
              </label>
              <div className="border-t border-gray-800 my-1" />
              {discoverServers.map((server) => (
                <label
                  key={server.name}
                  className="flex items-start gap-3 py-2 px-2 rounded hover:bg-gray-800 cursor-pointer select-none"
                >
                  <input
                    type="checkbox"
                    className="accent-blue-500 mt-0.5 shrink-0"
                    checked={selectedServers.has(server.name)}
                    onChange={(e) => {
                      setSelectedServers((prev) => {
                        const next = new Set(prev);
                        if (e.target.checked) next.add(server.name);
                        else next.delete(server.name);
                        return next;
                      });
                    }}
                  />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-white">{server.name}</p>
                    <p className="text-xs text-gray-500 truncate">{server.path}</p>
                  </div>
                </label>
              ))}
            </div>

            {/* Plugin + Agent selectors */}
            <div className="px-6 py-4 border-t border-gray-800 space-y-3 shrink-0">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-400 mb-1">Plugin</label>
                  <select
                    value={discoverPluginId}
                    onChange={(e) => setDiscoverPluginId(e.target.value)}
                    disabled={importBusy}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
                  >
                    {discoverPlugins.length === 0 && (
                      <option value="">No plugins</option>
                    )}
                    {discoverPlugins.map((p) => (
                      <option key={p.plugin_id} value={p.plugin_id}>
                        {p.display_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">
                    Agent{" "}
                    <span className="text-gray-600">(optional)</span>
                  </label>
                  <select
                    value={discoverAgentId}
                    onChange={(e) => setDiscoverAgentId(e.target.value)}
                    disabled={importBusy}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
                  >
                    <option value="">— None —</option>
                    {discoverAgents.map((a) => (
                      <option key={a.agent_id} value={a.agent_id}>
                        {a.machine_name}
                        {a.is_connected ? " ●" : " ○"}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {importError && (
                <pre className="text-xs text-red-400 bg-red-950/50 border border-red-800 rounded px-3 py-2 whitespace-pre-wrap">
                  {importError}
                </pre>
              )}

              <div className="flex items-center justify-between pt-1">
                <span className="text-xs text-gray-500">
                  {selectedServers.size} of {discoverServers.length} selected
                </span>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setShowDiscoverModal(false)}
                    disabled={importBusy}
                    className="px-4 py-2 rounded text-sm text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 transition-colors disabled:opacity-40"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleImport}
                    disabled={importBusy || selectedServers.size === 0 || !discoverPluginId}
                    className="px-4 py-2 rounded text-sm bg-blue-700 hover:bg-blue-600 text-white border border-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {importBusy
                      ? "Importing…"
                      : `Import Selected (${selectedServers.size})`}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── Add Server Modal ─────────────────────────────────────────────────── */}
      {showModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowModal(false);
          }}
        >
          <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-md mx-4">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
              <h2 className="text-lg font-semibold">Add Server</h2>
              <button
                onClick={() => setShowModal(false)}
                className="text-gray-500 hover:text-white text-xl leading-none"
              >
                ×
              </button>
            </div>

            <form onSubmit={handleAdd} className="px-6 py-5 space-y-4">
              {addError && (
                <div className="px-3 py-2 rounded bg-red-950 border border-red-800 text-red-300 text-sm">
                  {addError}
                </div>
              )}

              {modalLoading ? (
                <div className="text-gray-500 text-sm text-center py-4">Loading…</div>
              ) : (
                <>
                  {/* Name */}
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Name</label>
                    <input
                      type="text"
                      value={form.display_name}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, display_name: e.target.value }))
                      }
                      placeholder="e.g. TheIsland"
                      className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white placeholder-gray-600 focus:outline-none focus:border-blue-500"
                    />
                  </div>

                  {/* Plugin */}
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">Plugin</label>
                    <select
                      value={form.plugin_id}
                      onChange={(e) => handlePluginChange(e.target.value)}
                      className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                    >
                      {modalPlugins.length === 0 && (
                        <option value="">No plugins available</option>
                      )}
                      {modalPlugins.map((p) => (
                        <option key={p.plugin_id} value={p.plugin_id}>
                          {p.display_name} ({p.plugin_id})
                        </option>
                      ))}
                    </select>
                    {managedCreateRequiresAgent && (
                      <p className={`mt-1 text-xs ${connectedModalAgents.length > 0 ? "text-gray-500" : "text-red-400"}`}>
                        {connectedModalAgents.length > 0
                          ? "Managed ARK create requires a connected agent."
                          : "No connected agents are available. Managed ARK create needs an online host agent."}
                      </p>
                    )}
                  </div>

                  {selectedPluginMaps.length > 0 && (
                    <div>
                      <label className="block text-sm text-gray-400 mb-1">Map</label>
                      <select
                        value={form.map}
                        onChange={(e) =>
                          setForm((f) => ({
                            ...f,
                            display_name: f.display_name || e.target.value,
                            map: e.target.value,
                          }))
                        }
                        className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                      >
                        {selectedPluginMaps.map((mapOption) => (
                          <option key={mapOption.id} value={mapOption.id}>
                            {mapOption.display_name}
                          </option>
                        ))}
                      </select>
                      <p className="mt-1 text-xs text-gray-500">
                        Required for managed provisioning so the host layout and ports can be prepared.
                      </p>
                    </div>
                  )}

                  {/* Agent */}
                  <div>
                    <label className="block text-sm text-gray-400 mb-1">
                      Agent{" "}
                      <span className="text-gray-600">
                        {managedCreateRequiresAgent ? "(required for managed provisioning)" : "(optional)"}
                      </span>
                    </label>
                    <select
                      value={form.agent_id}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, agent_id: e.target.value }))
                      }
                      className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                    >
                      <option value="">— None —</option>
                      {modalAgents.map((a) => (
                        <option
                          key={a.agent_id}
                          value={a.agent_id}
                          disabled={managedCreateRequiresAgent && !a.is_connected}
                        >
                          {a.machine_name}
                          {a.is_connected ? " ● online" : " ○ offline"}
                        </option>
                      ))}
                    </select>
                  </div>
                </>
              )}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 rounded text-sm text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createDisabled}
                  className="px-4 py-2 rounded text-sm bg-blue-700 hover:bg-blue-600 text-white border border-blue-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {addBusy ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// ActionButton
// ─────────────────────────────────────────────────────────────────────────────

function ActionButton({
  label,
  busy,
  disabled,
  onClick,
  variant,
}: {
  label: string;
  busy: boolean;
  disabled: boolean;
  onClick: () => void;
  variant: "green" | "red" | "yellow";
}) {
  const base =
    "px-3 py-1 rounded text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
  const variants = {
    green: "bg-green-900 text-green-300 border border-green-700 hover:bg-green-800",
    red: "bg-red-900 text-red-300 border border-red-700 hover:bg-red-800",
    yellow: "bg-yellow-900 text-yellow-300 border border-yellow-700 hover:bg-yellow-800",
  };
  return (
    <button className={`${base} ${variants[variant]}`} disabled={disabled} onClick={onClick}>
      {busy ? "…" : label}
    </button>
  );
}
