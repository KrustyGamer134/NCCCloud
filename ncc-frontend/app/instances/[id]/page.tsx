"use client";

import Link from "next/link";
import { UserButton, useAuth } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";

import { fetchInstanceDetail, type InstanceDetailResponse } from "../../lib/api";

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

export default function InstanceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { getToken } = useAuth();
  const [instanceId, setInstanceId] = useState("");
  const [detail, setDetail] = useState<InstanceDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    } catch (e: any) {
      setError(e.message ?? "Failed to load instance detail");
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
  const installLogLines = detail?.logs.install_server?.data?.lines ?? detail?.install_progress?.data?.install_log_tail ?? [];
  const runtimeLogLines = detail?.logs.server?.data?.lines ?? [];

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
          <Link href="/settings" className="text-sm text-gray-400 hover:text-white transition-colors">
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
          </div>
          <button
            onClick={() => void loadDetail()}
            className="rounded border border-gray-700 px-3 py-1.5 text-sm text-gray-300 hover:border-gray-500 hover:text-white transition-colors"
          >
            Refresh
          </button>
        </div>

        {error && <div className="mb-4 rounded border border-red-800 bg-red-950 px-4 py-3 text-sm text-red-300">{error}</div>}

        {loading && !detail ? (
          <div className="py-12 text-center text-sm text-gray-500">Loading instance detail…</div>
        ) : detail ? (
          <div className="space-y-6">
            <section className="grid gap-4 md:grid-cols-4">
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="mb-2 text-xs uppercase tracking-wide text-gray-500">Lifecycle</div>
                <StatusBadge label={statusState} />
              </div>
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="mb-2 text-xs uppercase tracking-wide text-gray-500">Install</div>
                <StatusBadge label={installStatus} />
              </div>
              <div className="rounded-lg border border-gray-800 bg-gray-900 p-4">
                <div className="mb-2 text-xs uppercase tracking-wide text-gray-500">Progress</div>
                <StatusBadge label={progressState} />
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
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs text-gray-300">
                  {JSON.stringify(detail.install_progress?.data?.progress_metadata ?? {}, null, 2)}
                </pre>
              </div>
            </section>

            <div className="grid gap-4 lg:grid-cols-2">
              <LogBlock title="Install Log" lines={installLogLines} />
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
