"use client";

import Link from "next/link";
import { UserButton, useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";

import { fetchInstanceDetail, runInstanceAction, type InstanceDetailResponse } from "../../lib/api";

function StatusBadge({ label }: { label: string }) {
  const lowered = String(label || "unknown").toLowerCase();
  const style =
    lowered === "running" || lowered === "started"
      ? "bg-green-900 text-green-300 border-green-700"
      : lowered === "starting" || lowered === "stopping" || lowered === "restarting"
      ? "bg-yellow-900 text-yellow-300 border-yellow-700"
      : lowered === "failed" || lowered === "error"
      ? "bg-red-900 text-red-300 border-red-700"
      : "bg-gray-800 text-gray-300 border-gray-700";

  return <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${style}`}>{label}</span>;
}

function LogBlock({ title, lines }: { title: string; lines: string[] }) {
  return (
    <section className="rounded-lg border border-gray-800 bg-gray-900">
      <div className="border-b border-gray-800 px-4 py-3 text-sm font-medium text-white">{title}</div>
      <pre className="max-h-80 overflow-auto px-4 py-3 text-xs text-gray-300 whitespace-pre-wrap">
        {lines.length > 0 ? lines.join("\n") : "No log lines available."}
      </pre>
    </section>
  );
}

const ACTIVE_INSTALL_STATES = new Set(["queued", "running", "installing"]);
const ACTIVE_START_STATES = new Set(["starting", "restarting"]);

function normalizeState(value: unknown, fallback = "unknown") {
  const normalized = String(value ?? "").trim().toLowerCase();
  return normalized || fallback;
}

function titleCaseState(value: string) {
  return String(value || "unknown")
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}

function deriveDetailView(args: {
  statusState: string;
  installStatus: string;
  progressState: string;
  runtimeRunning: boolean;
  runtimeReady: boolean;
  pendingAction: string | null;
}) {
  const pendingAction = normalizeState(args.pendingAction, "");
  const lifecycle = pendingAction === "start"
    ? "starting"
    : pendingAction === "restart"
    ? "restarting"
    : pendingAction === "stop"
    ? "stopping"
    : normalizeState(args.statusState);
  const install = pendingAction === "install-server" ? "installing" : normalizeState(args.installStatus);
  const progress = pendingAction === "install-server"
    ? "running"
    : pendingAction === "start" || pendingAction === "restart"
    ? "starting"
    : normalizeState(args.progressState, "not_started");
  const runtimeRunning = Boolean(args.runtimeRunning);
  const runtimeReady = Boolean(args.runtimeReady);

  const installActive = ACTIVE_INSTALL_STATES.has(progress) || ACTIVE_INSTALL_STATES.has(install);
  const startActive = ACTIVE_START_STATES.has(lifecycle) || progress === "starting";
  const stopActive = lifecycle === "stopping";
  const failed = progress === "failed" || progress === "error" || install === "failed" || install === "error";
  const installed = !["not_installed", "unknown"].includes(install);
  const running = lifecycle === "running" || lifecycle === "started" || runtimeReady;

  const lifecycleBadge = installActive
    ? "Installing"
    : startActive
    ? lifecycle === "restarting"
      ? "Restarting"
      : "Starting"
    : stopActive
    ? "Stopping"
    : titleCaseState(lifecycle);

  const installBadge = installActive
    ? "Installing"
    : failed
    ? "Failed"
    : installed
    ? "Installed"
    : "Not Installed";

  const progressBadge = installActive
    ? titleCaseState(progress === "not_started" ? "running" : progress)
    : startActive
    ? lifecycle === "restarting"
      ? "Restarting"
      : "Starting"
    : stopActive
    ? "Stopping"
    : failed
    ? "Failed"
    : "Idle";

  return {
    installActive,
    startActive,
    stopActive,
    failed,
    installed,
    running,
    runtimeRunning,
    runtimeReady,
    lifecycle,
    install,
    progress,
    lifecycleBadge,
    installBadge,
    progressBadge,
  };
}

function resolveRecommendedAction(args: {
  installActive: boolean;
  startActive: boolean;
  stopActive: boolean;
  failed: boolean;
  installed: boolean;
  running: boolean;
  runtimeReady: boolean;
}) {
  if (args.installActive) {
    return {
      title: "Installation in progress",
      body: "The host is still working. Stay on this page to watch logs and progress update.",
      action: null,
    };
  }

  if (args.startActive) {
    return {
      title: "Startup in progress",
      body: "The host accepted the start request. Wait for runtime readiness and current logs before taking another action.",
      action: null,
    };
  }

  if (args.stopActive) {
    return {
      title: "Shutdown in progress",
      body: "The host is reconciling the stop request. Wait for the runtime state to settle before the next action.",
      action: null,
    };
  }

  if (!args.installed || args.failed) {
    return {
      title: "Install the server",
      body: "Managed provisioning is complete. Run Install next to place the ARK server files on the host.",
      action: "install-server" as const,
    };
  }

  if (!args.running && !args.runtimeReady) {
    return {
      title: "Start the server",
      body: "The server files are in place. Start the instance to launch the ARK runtime and confirm readiness.",
      action: "start" as const,
    };
  }

  return {
    title: "Server is manageable",
    body: "Use Stop or Restart as needed and monitor runtime state and logs from this page.",
    action: null,
  };
}

function actionLabel(action: "install-server" | "start" | "stop" | "restart") {
  switch (action) {
    case "install-server":
      return "Install";
    case "start":
      return "Start";
    case "stop":
      return "Stop";
    case "restart":
      return "Restart";
  }
}

export default function InstanceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { getToken } = useAuth();
  const [instanceId, setInstanceId] = useState("");
  const [detail, setDetail] = useState<InstanceDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    params.then((value) => {
      if (mounted) setInstanceId(value.id);
    });
    return () => {
      mounted = false;
    };
  }, [params]);

  const loadDetail = useCallback(async () => {
    if (!instanceId) return;
    setLoading(true);
    try {
      const token = await getToken();
      const payload = await fetchInstanceDetail(token!, instanceId);
      setDetail(payload);
      setError(null);
    } catch (error: unknown) {
      setError(errorMessage(error, "Failed to load instance detail"));
    } finally {
      setLoading(false);
    }
  }, [getToken, instanceId]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const statusState = detail?.status?.data?.state ?? detail?.instance.status ?? "unknown";
  const installStatus = detail?.status?.data?.install_status ?? detail?.instance.install_status ?? "unknown";
  const progressState = detail?.install_progress?.data?.state ?? "not_started";
  const runtimeRunning = Boolean(detail?.status?.data?.runtime_running);
  const runtimeReady = Boolean(detail?.status?.data?.runtime_ready);
  const installLogLines = detail?.logs.install_server?.data?.lines ?? detail?.install_progress?.data?.install_log_tail ?? [];
  const steamcmdLogLines = detail?.install_progress?.data?.steamcmd_log_tail ?? [];
  const runtimeLogLines = detail?.logs.server?.data?.lines ?? [];
  const configuredMap = String(detail?.instance.config_json?.map ?? "unset");
  const agentOnline = Boolean(detail?.instance.agent_online);
  const pendingConfigFields = detail?.config_apply?.data?.pending_fields ?? [];
  const configRequiresRestart = Boolean(detail?.config_apply?.data?.requires_restart);
  const view = deriveDetailView({
    statusState,
    installStatus,
    progressState,
    runtimeRunning,
    runtimeReady,
    pendingAction,
  });
  const shouldAutoRefresh =
    pendingAction !== null ||
    view.installActive ||
    view.startActive ||
    view.stopActive;
  const recommendedAction = resolveRecommendedAction(view);
  const actionDisabled = {
    "install-server":
      !agentOnline ||
      pendingAction !== null ||
      view.installActive ||
      view.startActive ||
      view.stopActive ||
      view.runtimeRunning ||
      (view.installed && !view.failed),
    start: !agentOnline || pendingAction !== null || view.installActive || view.startActive || view.stopActive || !view.installed || view.running,
    stop: !agentOnline || pendingAction !== null || view.installActive || view.stopActive || (!view.running && !view.startActive && !view.runtimeRunning),
    restart: !agentOnline || pendingAction !== null || view.installActive || view.startActive || view.stopActive || !view.installed || !view.running,
  } as const;
  const progressSummary = view.installActive
    ? "Install progress is coming from the host installer state and SteamCMD metadata."
    : view.startActive
    ? "Startup progress is coming from the lifecycle snapshot and runtime readiness."
    : view.stopActive
    ? "Shutdown progress is coming from the lifecycle snapshot while the host reconciles runtime state."
    : "No active install or lifecycle transition is reported by the backend.";

  useEffect(() => {
    if (!instanceId || !shouldAutoRefresh) return;

    const timer = window.setTimeout(() => {
      void loadDetail();
    }, 3000);

    return () => window.clearTimeout(timer);
  }, [detail, instanceId, loadDetail, shouldAutoRefresh]);

  async function handleAction(action: "install-server" | "start" | "stop" | "restart") {
    if (!instanceId) return;
    setPendingAction(action);
    try {
      const token = await getToken();
      await runInstanceAction(token!, instanceId, action);
      await loadDetail();
    } catch (error: unknown) {
      setError(errorMessage(error, `Failed to ${action}`));
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <nav className="flex items-center justify-between border-b border-gray-800 px-6 py-4">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-xl font-bold text-white hover:text-gray-300">
            NCC
          </Link>
          <span className="text-sm text-gray-500">Instance Detail</span>
        </div>
        <div className="flex items-center gap-4">
          <Link href="/instances" className="text-sm text-gray-400 hover:text-white transition-colors">
            Game Servers
          </Link>
          <Link
            href={`/settings?tab=instances&instanceId=${encodeURIComponent(instanceId)}`}
            className="text-sm text-gray-400 hover:text-white transition-colors"
          >
            Settings
          </Link>
          <UserButton />
        </div>
      </nav>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <div className="mb-6 flex items-center justify-between gap-3">
          <div>
            <div className="mb-2">
              <Link href="/instances" className="text-sm text-gray-500 hover:text-gray-300 transition-colors">
                Back to instances
              </Link>
            </div>
            <h1 className="text-3xl font-bold">{detail?.instance.display_name ?? "Instance"}</h1>
            <p className="mt-1 text-sm text-gray-500">{detail?.instance.plugin_id ?? "loading"} · {instanceId}</p>
            <p className="mt-1 text-sm text-gray-500">Map: <span className="text-gray-300">{configuredMap}</span></p>
          </div>
          <div className="flex items-center gap-2">
            {shouldAutoRefresh && (
              <span className="text-xs text-gray-500">Auto-refreshing</span>
            )}
            {!agentOnline && (
              <span className="text-xs text-red-400">Agent offline</span>
            )}
            <button
              onClick={() => void handleAction("install-server")}
              disabled={actionDisabled["install-server"]}
              className="rounded border border-blue-700 bg-blue-900 px-3 py-1.5 text-sm text-blue-200 hover:border-blue-500 hover:text-white transition-colors disabled:opacity-50"
            >
              {pendingAction === "install-server" ? "Installing..." : "Install"}
            </button>
            <button
              onClick={() => void handleAction("start")}
              disabled={actionDisabled.start}
              className="rounded border border-green-700 bg-green-900 px-3 py-1.5 text-sm text-green-200 hover:border-green-500 hover:text-white transition-colors disabled:opacity-50"
            >
              {pendingAction === "start" ? "Starting..." : "Start"}
            </button>
            <button
              onClick={() => void handleAction("stop")}
              disabled={actionDisabled.stop}
              className="rounded border border-red-700 bg-red-900 px-3 py-1.5 text-sm text-red-200 hover:border-red-500 hover:text-white transition-colors disabled:opacity-50"
            >
              {pendingAction === "stop" ? "Stopping..." : "Stop"}
            </button>
            <button
              onClick={() => void handleAction("restart")}
              disabled={actionDisabled.restart}
              className="rounded border border-yellow-700 bg-yellow-900 px-3 py-1.5 text-sm text-yellow-200 hover:border-yellow-500 hover:text-white transition-colors disabled:opacity-50"
            >
              {pendingAction === "restart" ? "Restarting..." : "Restart"}
            </button>
            <button
              onClick={() => void loadDetail()}
              className="rounded border border-gray-700 px-3 py-1.5 text-sm text-gray-300 hover:border-gray-500 hover:text-white transition-colors"
            >
              Refresh
            </button>
          </div>
        </div>

        {error && <div className="mb-4 rounded border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">{error}</div>}

        {loading && !detail ? (
          <div className="py-12 text-center text-sm text-gray-500">Loading instance detail…</div>
        ) : detail ? (
          <div className="space-y-6">
            <section className="rounded-lg border border-blue-800 bg-blue-950/40 p-4">
            <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="text-xs uppercase tracking-wide text-blue-300">Next Step</div>
                  <div className="mt-2 text-sm font-medium text-white">{recommendedAction.title}</div>
                  <p className="mt-1 text-sm text-blue-100/80">{recommendedAction.body}</p>
                  <div className="mt-3">
                    <Link
                      href={`/settings?tab=instances&instanceId=${encodeURIComponent(instanceId)}`}
                      className="text-sm text-blue-300 hover:text-white transition-colors"
                    >
                      Open instance configuration
                    </Link>
                  </div>
                  <div className="mt-3 text-xs text-blue-100/70">
                    {`Map ${configuredMap} • Game ${String(detail.instance.config_json?.game_port ?? "unset")} • RCON ${String(detail.instance.config_json?.rcon_port ?? "unset")}`}
                  </div>
                  {configRequiresRestart && (
                    <div className="mt-3 text-xs text-yellow-200/90">
                      {`Config changes are pending host apply after stop/start: ${pendingConfigFields.join(", ")}`}
                    </div>
                  )}
                </div>
                {recommendedAction.action && (
                  <button
                    onClick={() => void handleAction(recommendedAction.action)}
                    disabled={actionDisabled[recommendedAction.action]}
                    className="shrink-0 rounded border border-blue-600 bg-blue-800 px-3 py-1.5 text-sm text-white hover:border-blue-500 hover:bg-blue-700 transition-colors disabled:opacity-50"
                  >
                    {pendingAction === recommendedAction.action
                      ? `${actionLabel(recommendedAction.action)}ing...`
                      : actionLabel(recommendedAction.action)}
                  </button>
                )}
              </div>
            </section>

            <section className="grid gap-4 md:grid-cols-4">
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="mb-2 text-xs uppercase tracking-wide text-gray-500">Lifecycle</div>
                <StatusBadge label={view.lifecycleBadge} />
              </div>
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="mb-2 text-xs uppercase tracking-wide text-gray-500">Install</div>
                <StatusBadge label={view.installBadge} />
              </div>
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="mb-2 text-xs uppercase tracking-wide text-gray-500">Progress</div>
                <StatusBadge label={view.progressBadge} />
              </div>
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="mb-2 text-xs uppercase tracking-wide text-gray-500">Agent</div>
                <StatusBadge label={detail.instance.agent_online ? "online" : "offline"} />
              </div>
            </section>

            <section className="grid gap-4 md:grid-cols-2">
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="mb-3 text-sm font-medium text-white">Status Snapshot</div>
                <dl className="space-y-2 text-sm text-gray-300">
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">Runtime running</dt>
                    <dd>{String(Boolean(detail.status?.data?.runtime_running))}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">Runtime ready</dt>
                    <dd>{String(Boolean(detail.status?.data?.runtime_ready))}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">Configured map</dt>
                    <dd>{String(detail.instance.config_json?.map ?? "unset")}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">Game port</dt>
                    <dd>{String(detail.instance.config_json?.game_port ?? "unset")}</dd>
                  </div>
                  <div className="flex justify-between gap-3">
                    <dt className="text-gray-500">RCON port</dt>
                    <dd>{String(detail.instance.config_json?.rcon_port ?? "unset")}</dd>
                  </div>
                </dl>
              </div>

              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="mb-3 text-sm font-medium text-white">Install Metadata</div>
                <p className="mb-3 text-xs text-gray-500">{progressSummary}</p>
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs text-gray-300">
                  {JSON.stringify(detail.install_progress?.data?.progress_metadata ?? {}, null, 2)}
                </pre>
              </div>
            </section>

            <div className="grid gap-4 lg:grid-cols-3">
              <LogBlock title="Install Log" lines={installLogLines} />
              <LogBlock title="SteamCMD Log" lines={steamcmdLogLines} />
              <LogBlock title="Runtime Log" lines={runtimeLogLines} />
            </div>
          </div>
        ) : (
          <div className="py-12 text-center text-sm text-gray-500">No instance detail available.</div>
        )}
      </main>
    </div>
  );
}
