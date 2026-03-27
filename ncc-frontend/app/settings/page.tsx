"use client";

import { useAuth, UserButton } from "@clerk/nextjs";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  fetchAppSettings,
  saveAppSettings,
  fetchPlugins,
  fetchPluginSettings,
  savePluginSettings,
  fetchInstances,
  saveInstanceConfig,
  type InstanceConfigSaveResponse,
} from "../lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface Plugin {
  plugin_id: string;
  display_name: string;
  description: string | null;
}

interface Instance {
  instance_id: string;
  display_name: string;
  plugin_id: string;
  status: string;
  config_json: Record<string, unknown>;
}

type Tab = "app" | "plugins" | "instances";

// ─────────────────────────────────────────────────────────────────────────────
// Form types
// ─────────────────────────────────────────────────────────────────────────────

interface AppForm {
  // Cluster config (sent to agent / cluster_config.json)
  gameservers_root: string;
  steamcmd_root: string;
  cluster_name: string;
  // UI preferences (web-client only)
  auto_refresh_enabled: boolean;
  auto_refresh_interval_seconds: number;
  max_log_lines_shown: number;
  auto_scroll_logs: boolean;
  show_confirmation_dialogs: boolean;
}

interface PluginForm {
  display_name: string;
  cluster_id: string;
  mods: string;          // one per line
  passive_mods: string;  // one per line
  admin_password: string;
  rcon_enabled: boolean;
  pve: boolean;
  auto_update_on_restart: boolean;
  max_players: string;
  test_mode: boolean;
  install_root: string;
  scheduled_update_check_enabled: boolean;
  scheduled_update_check_time: string;
  scheduled_update_auto_apply: boolean;
  scheduled_restart_enabled: boolean;
  scheduled_restart_time: string;
  default_game_port_start: string;
  default_rcon_port_start: string;
}

interface InstanceForm {
  map: string;           // read-only
  game_port: string;
  rcon_port: string;
  rcon_enabled: boolean;
  admin_password: string;
  max_players: string;
  server_name: string;
  mods: string;          // one per line
  passive_mods: string;  // one per line
  map_mod: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Converters
// ─────────────────────────────────────────────────────────────────────────────

const DEFAULT_APP: AppForm = {
  gameservers_root: "",
  steamcmd_root: "",
  cluster_name: "arkSA",
  auto_refresh_enabled: true,
  auto_refresh_interval_seconds: 2,
  max_log_lines_shown: 200,
  auto_scroll_logs: true,
  show_confirmation_dialogs: true,
};

function appJsonToForm(json: Record<string, unknown>): AppForm {
  return {
    gameservers_root: String(json.gameservers_root ?? ""),
    steamcmd_root: String(json.steamcmd_root ?? ""),
    cluster_name: String(json.cluster_name ?? "arkSA"),
    auto_refresh_enabled: json.auto_refresh_enabled !== false,
    auto_refresh_interval_seconds: Number(json.auto_refresh_interval_seconds ?? 2),
    max_log_lines_shown: Number(json.max_log_lines_shown ?? 200),
    auto_scroll_logs: json.auto_scroll_logs !== false,
    show_confirmation_dialogs: json.show_confirmation_dialogs !== false,
  };
}

function formToAppJson(form: AppForm): Record<string, unknown> {
  return {
    gameservers_root: form.gameservers_root.trim(),
    steamcmd_root: form.steamcmd_root.trim(),
    cluster_name: form.cluster_name.trim() || "arkSA",
    auto_refresh_enabled: form.auto_refresh_enabled,
    auto_refresh_interval_seconds: form.auto_refresh_interval_seconds,
    max_log_lines_shown: Math.max(1, Math.min(2000, form.max_log_lines_shown)),
    auto_scroll_logs: form.auto_scroll_logs,
    show_confirmation_dialogs: form.show_confirmation_dialogs,
  };
}

const DEFAULT_PLUGIN: PluginForm = {
  display_name: "",
  cluster_id: "",
  mods: "",
  passive_mods: "",
  admin_password: "",
  rcon_enabled: true,
  pve: true,
  auto_update_on_restart: false,
  max_players: "",
  test_mode: false,
  install_root: "",
  scheduled_update_check_enabled: false,
  scheduled_update_check_time: "",
  scheduled_update_auto_apply: false,
  scheduled_restart_enabled: false,
  scheduled_restart_time: "",
  default_game_port_start: "",
  default_rcon_port_start: "",
};

function pluginJsonToForm(json: Record<string, unknown>): PluginForm {
  const toLines = (v: unknown) =>
    Array.isArray(v) ? v.join("\n") : String(v ?? "");
  return {
    display_name: String(json.display_name ?? ""),
    cluster_id: String(json.cluster_id ?? ""),
    mods: toLines(json.mods),
    passive_mods: toLines(json.passive_mods),
    admin_password: String(json.admin_password ?? ""),
    rcon_enabled: json.rcon_enabled !== false,
    pve: json.pve !== false,
    auto_update_on_restart: Boolean(json.auto_update_on_restart),
    max_players: json.max_players != null ? String(json.max_players) : "",
    test_mode: Boolean(json.test_mode),
    install_root: String(json.install_root ?? ""),
    scheduled_update_check_enabled: Boolean(json.scheduled_update_check_enabled),
    scheduled_update_check_time: String(json.scheduled_update_check_time ?? ""),
    scheduled_update_auto_apply: Boolean(json.scheduled_update_auto_apply),
    scheduled_restart_enabled: Boolean(json.scheduled_restart_enabled),
    scheduled_restart_time: String(json.scheduled_restart_time ?? ""),
    default_game_port_start:
      json.default_game_port_start != null ? String(json.default_game_port_start) : "",
    default_rcon_port_start:
      json.default_rcon_port_start != null ? String(json.default_rcon_port_start) : "",
  };
}

function formToPluginJson(form: PluginForm): Record<string, unknown> {
  const toList = (s: string) =>
    s
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
  const out: Record<string, unknown> = {
    mods: toList(form.mods),
    passive_mods: toList(form.passive_mods),
    rcon_enabled: form.rcon_enabled,
    pve: form.pve,
    auto_update_on_restart: form.auto_update_on_restart,
    test_mode: form.test_mode,
    scheduled_update_check_enabled: form.scheduled_update_check_enabled,
    scheduled_update_auto_apply: form.scheduled_update_auto_apply,
    scheduled_restart_enabled: form.scheduled_restart_enabled,
  };
  if (form.display_name.trim()) out.display_name = form.display_name.trim();
  if (form.cluster_id.trim()) out.cluster_id = form.cluster_id.trim();
  if (form.admin_password.trim()) out.admin_password = form.admin_password.trim();
  if (form.max_players.trim()) out.max_players = parseInt(form.max_players, 10);
  if (form.install_root.trim()) out.install_root = form.install_root.trim();
  if (form.scheduled_update_check_time.trim())
    out.scheduled_update_check_time = form.scheduled_update_check_time.trim();
  if (form.scheduled_restart_time.trim())
    out.scheduled_restart_time = form.scheduled_restart_time.trim();
  if (form.default_game_port_start.trim())
    out.default_game_port_start = parseInt(form.default_game_port_start, 10);
  if (form.default_rcon_port_start.trim())
    out.default_rcon_port_start = parseInt(form.default_rcon_port_start, 10);
  return out;
}

function instanceConfigToForm(config: Record<string, unknown>): InstanceForm {
  const toLines = (v: unknown) =>
    Array.isArray(v) ? v.join("\n") : String(v ?? "");
  return {
    map: String(config.map ?? ""),
    game_port: config.game_port != null ? String(config.game_port) : "",
    rcon_port: config.rcon_port != null ? String(config.rcon_port) : "",
    rcon_enabled: config.rcon_enabled !== false,
    admin_password: String(config.admin_password ?? ""),
    max_players: config.max_players != null ? String(config.max_players) : "",
    server_name: String(config.server_name ?? ""),
    mods: toLines(config.mods),
    passive_mods: toLines(config.passive_mods),
    map_mod: String(config.map_mod ?? ""),
  };
}

function formToInstanceConfig(form: InstanceForm): Record<string, unknown> {
  const toList = (s: string) =>
    s
      .split("\n")
      .map((x) => x.trim())
      .filter(Boolean);
  const out: Record<string, unknown> = {
    map: form.map.trim(),
    rcon_enabled: form.rcon_enabled,
    mods: toList(form.mods),
    passive_mods: toList(form.passive_mods),
  };
  if (form.game_port.trim()) out.game_port = parseInt(form.game_port, 10);
  if (form.rcon_port.trim()) out.rcon_port = parseInt(form.rcon_port, 10);
  if (form.admin_password.trim()) out.admin_password = form.admin_password.trim();
  if (form.max_players.trim()) out.max_players = parseInt(form.max_players, 10);
  if (form.server_name.trim()) out.server_name = form.server_name.trim();
  if (form.map_mod.trim()) out.map_mod = form.map_mod.trim();
  return out;
}

// ─────────────────────────────────────────────────────────────────────────────
// Validation
// ─────────────────────────────────────────────────────────────────────────────

function isValidHHMM(v: string): boolean {
  if (!v.trim()) return true;
  if (!/^\d{2}:\d{2}$/.test(v.trim())) return false;
  const [h, m] = v.trim().split(":").map(Number);
  return h <= 23 && m <= 59;
}

function isValidPort(v: string): boolean {
  if (!v.trim()) return true;
  const n = parseInt(v, 10);
  return !isNaN(n) && n >= 1 && n <= 65535;
}

function validatePluginForm(f: PluginForm): string | null {
  const mods = f.mods
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const passive = f.passive_mods
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  if (new Set(mods).size !== mods.length) return "Mods list contains duplicates.";
  if (new Set(passive).size !== passive.length) return "Passive mods list contains duplicates.";
  if (mods.some((m) => passive.includes(m))) return "Mods and passive mods must stay separate.";
  if (!isValidHHMM(f.scheduled_update_check_time))
    return "Update Check Time must use HH:MM 24-hour format.";
  if (!isValidHHMM(f.scheduled_restart_time))
    return "Scheduled Restart Time must use HH:MM 24-hour format.";
  for (const [label, val] of [
    ["Max Players", f.max_players],
    ["Game Port Start", f.default_game_port_start],
    ["RCON Port Start", f.default_rcon_port_start],
  ] as [string, string][]) {
    if (!isValidPort(val)) return `${label} must be a number between 1 and 65535.`;
  }
  return null;
}

function validateInstanceForm(f: InstanceForm): string | null {
  for (const [label, val] of [
    ["Game port", f.game_port],
    ["RCON port", f.rcon_port],
    ["Max players", f.max_players],
  ] as [string, string][]) {
    if (!isValidPort(val)) return `${label} must be a number between 1 and 65535.`;
  }
  if (
    f.game_port.trim() &&
    f.rcon_port.trim() &&
    f.game_port.trim() === f.rcon_port.trim()
  )
    return "Game port and RCON port must be different.";
  const mods = f.mods
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  const passive = f.passive_mods
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  if (new Set(mods).size !== mods.length) return "Mods list contains duplicates.";
  if (new Set(passive).size !== passive.length) return "Passive mods list contains duplicates.";
  if (mods.some((m) => passive.includes(m))) return "Mods and passive mods must stay separate.";
  return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Primitive form components
// ─────────────────────────────────────────────────────────────────────────────

function FieldRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-4 py-2.5">
      <div className="w-52 shrink-0 pt-1">
        <span className="text-sm text-gray-300">{label}</span>
        {hint && <p className="text-xs text-gray-600 mt-0.5">{hint}</p>}
      </div>
      <div className="flex-1">{children}</div>
    </div>
  );
}

function FieldGroup({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-5 first:mt-0">
      <p className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-1 pb-1 border-b border-gray-800">
        {title}
      </p>
      <div className="divide-y divide-gray-800/40">{children}</div>
    </div>
  );
}

const inputCls =
  "w-full bg-gray-950 border border-gray-700 rounded text-sm text-gray-200 px-3 py-1.5 focus:outline-none focus:border-gray-500 placeholder-gray-600";

function TextInput({
  value,
  onChange,
  placeholder,
  disabled,
  type = "text",
}: {
  value: string;
  onChange?: (v: string) => void;
  placeholder?: string;
  disabled?: boolean;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      className={`${inputCls} ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
    />
  );
}

function NumInput({
  value,
  onChange,
  placeholder,
  min = 1,
  max = 65535,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  min?: number;
  max?: number;
}) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      min={min}
      max={max}
      className={inputCls}
    />
  );
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none ${
        checked ? "bg-blue-600" : "bg-gray-600"
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
          checked ? "translate-x-4" : "translate-x-1"
        }`}
      />
    </button>
  );
}

function ModsArea({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      rows={4}
      spellCheck={false}
      className="w-full bg-gray-950 border border-gray-700 rounded font-mono text-sm text-gray-200 px-3 py-1.5 focus:outline-none focus:border-gray-500 placeholder-gray-600 resize-y"
    />
  );
}

function SaveRow({
  saving,
  success,
  error,
  onSave,
  label = "Save",
}: {
  saving: boolean;
  success: boolean;
  error: string | null;
  onSave: () => void;
  label?: string;
}) {
  return (
    <div className="mt-5 flex items-center justify-between pt-4 border-t border-gray-800">
      <div className="text-sm min-h-[1.25rem]">
        {error && <span className="text-red-400">{error}</span>}
        {!error && success && <span className="text-green-400">Saved.</span>}
      </div>
      <button
        onClick={onSave}
        disabled={saving}
        className="px-5 py-2 rounded text-sm font-medium bg-blue-700 hover:bg-blue-600 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {saving ? "Saving…" : label}
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: App Settings
// ─────────────────────────────────────────────────────────────────────────────

function AppSettingsTab({
  initial,
  onSaved,
  getToken,
}: {
  initial: Record<string, unknown>;
  onSaved: (json: Record<string, unknown>) => void;
  getToken: () => Promise<string | null>;
}) {
  const [form, setForm] = useState<AppForm>(() => appJsonToForm(initial));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const set = <K extends keyof AppForm>(k: K, v: AppForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const token = await getToken();
      const data = await saveAppSettings(token!, formToAppJson(form));
      onSaved(data.settings_json);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e: any) {
      setError(e.message ?? "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <p className="text-gray-500 text-sm mb-6">
        Tenant-level configuration. Cluster paths are forwarded to the agent with
        every command so the correct server directories are used.
      </p>

      <div className="bg-gray-900 rounded-lg border border-gray-800 p-5">
        <FieldGroup title="Cluster Paths">
          <FieldRow
            label="GameServers Root"
            hint="Root folder where game servers are installed, e.g. E:\GameServers"
          >
            <TextInput
              value={form.gameservers_root}
              onChange={(v) => set("gameservers_root", v)}
              placeholder="E:\GameServers"
            />
          </FieldRow>
          <FieldRow
            label="SteamCMD Root"
            hint="Path to the SteamCMD installation directory"
          >
            <TextInput
              value={form.steamcmd_root}
              onChange={(v) => set("steamcmd_root", v)}
              placeholder="E:\SteamCMD"
            />
          </FieldRow>
          <FieldRow
            label="Cluster Name"
            hint='Sub-folder name used for cluster data, default "arkSA"'
          >
            <TextInput
              value={form.cluster_name}
              onChange={(v) => set("cluster_name", v)}
              placeholder="arkSA"
            />
          </FieldRow>
        </FieldGroup>

        <FieldGroup title="UI Preferences">
          <FieldRow label="Auto-refresh">
            <Toggle
              checked={form.auto_refresh_enabled}
              onChange={(v) => set("auto_refresh_enabled", v)}
            />
          </FieldRow>
          <FieldRow label="Refresh interval (s)">
            <select
              value={form.auto_refresh_interval_seconds}
              onChange={(e) =>
                set("auto_refresh_interval_seconds", Number(e.target.value))
              }
              className="bg-gray-950 border border-gray-700 rounded text-sm text-gray-200 px-3 py-1.5 focus:outline-none focus:border-gray-500"
            >
              {[2, 5, 10, 30].map((n) => (
                <option key={n} value={n}>
                  {n}s
                </option>
              ))}
            </select>
          </FieldRow>
          <FieldRow label="Max log lines shown" hint="1 – 2000">
            <NumInput
              value={String(form.max_log_lines_shown)}
              onChange={(v) => set("max_log_lines_shown", Number(v))}
              placeholder="200"
              min={1}
              max={2000}
            />
          </FieldRow>
          <FieldRow label="Auto-scroll logs">
            <Toggle
              checked={form.auto_scroll_logs}
              onChange={(v) => set("auto_scroll_logs", v)}
            />
          </FieldRow>
          <FieldRow label="Show confirmation dialogs">
            <Toggle
              checked={form.show_confirmation_dialogs}
              onChange={(v) => set("show_confirmation_dialogs", v)}
            />
          </FieldRow>
        </FieldGroup>

        <SaveRow
          saving={saving}
          success={success}
          error={error}
          onSave={handleSave}
          label="Save App Settings"
        />
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Plugin Defaults
// ─────────────────────────────────────────────────────────────────────────────

function PluginDefaultsTab({
  plugins,
  getToken,
}: {
  plugins: Plugin[];
  getToken: () => Promise<string | null>;
}) {
  const [activePlugin, setActivePlugin] = useState<string | null>(null);
  const [form, setForm] = useState<PluginForm>(DEFAULT_PLUGIN);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const set = <K extends keyof PluginForm>(k: K, v: PluginForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  async function selectPlugin(id: string) {
    setActivePlugin(id);
    setError(null);
    setSuccess(false);
    setLoading(true);
    try {
      const token = await getToken();
      const data = await fetchPluginSettings(token!, id);
      setForm(pluginJsonToForm(data.plugin_json ?? {}));
    } catch (e: any) {
      setError(e.message ?? "Failed to load plugin settings.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    if (!activePlugin) return;
    const validErr = validatePluginForm(form);
    if (validErr) { setError(validErr); return; }
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const token = await getToken();
      await savePluginSettings(token!, activePlugin, formToPluginJson(form));
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (e: any) {
      setError(e.message ?? "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <p className="text-gray-500 text-sm mb-6">
        Default configuration for each plugin. Values are forwarded to the agent
        on every command and applied cluster-wide before per-instance overrides.
      </p>

      {plugins.length === 0 ? (
        <p className="text-gray-500 text-sm">No plugins in catalog.</p>
      ) : (
        <div className="flex gap-4">
          {/* Sidebar */}
          <div className="w-44 shrink-0 space-y-0.5">
            {plugins.map((p) => (
              <button
                key={p.plugin_id}
                onClick={() => selectPlugin(p.plugin_id)}
                className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                  activePlugin === p.plugin_id
                    ? "bg-gray-700 text-white"
                    : "text-gray-400 hover:bg-gray-800 hover:text-white"
                }`}
              >
                {p.display_name}
              </button>
            ))}
          </div>

          {/* Form panel */}
          <div className="flex-1 bg-gray-900 rounded-lg border border-gray-800 p-5">
            {activePlugin === null ? (
              <p className="text-gray-500 text-sm">
                Select a plugin from the list to edit its defaults.
              </p>
            ) : loading ? (
              <p className="text-gray-500 text-sm">Loading…</p>
            ) : (
              <>
                <FieldGroup title="General">
                  <FieldRow label="Display name">
                    <TextInput
                      value={form.display_name}
                      onChange={(v) => set("display_name", v)}
                      placeholder="ARK: Survival Ascended"
                    />
                  </FieldRow>
                  <FieldRow
                    label="Cluster ID"
                    hint="Shared cluster token for cross-server travel"
                  >
                    <TextInput
                      value={form.cluster_id}
                      onChange={(v) => set("cluster_id", v)}
                      placeholder="my-cluster"
                    />
                  </FieldRow>
                </FieldGroup>

                <FieldGroup title="Mods">
                  <FieldRow label="Active mods" hint="One mod ID per line">
                    <ModsArea
                      value={form.mods}
                      onChange={(v) => set("mods", v)}
                      placeholder={"927090\n895711"}
                    />
                  </FieldRow>
                  <FieldRow label="Passive mods" hint="One mod ID per line">
                    <ModsArea
                      value={form.passive_mods}
                      onChange={(v) => set("passive_mods", v)}
                      placeholder={"123456"}
                    />
                  </FieldRow>
                </FieldGroup>

                <FieldGroup title="Server">
                  <FieldRow label="Admin password">
                    <TextInput
                      value={form.admin_password}
                      onChange={(v) => set("admin_password", v)}
                      type="password"
                      placeholder="••••••••"
                    />
                  </FieldRow>
                  <FieldRow label="RCON enabled">
                    <Toggle
                      checked={form.rcon_enabled}
                      onChange={(v) => set("rcon_enabled", v)}
                    />
                  </FieldRow>
                  <FieldRow label="PvE mode">
                    <Toggle
                      checked={form.pve}
                      onChange={(v) => set("pve", v)}
                    />
                  </FieldRow>
                  <FieldRow label="Auto-update on restart">
                    <Toggle
                      checked={form.auto_update_on_restart}
                      onChange={(v) => set("auto_update_on_restart", v)}
                    />
                  </FieldRow>
                  <FieldRow label="Max players" hint="1 – 65535">
                    <NumInput
                      value={form.max_players}
                      onChange={(v) => set("max_players", v)}
                      placeholder="20"
                    />
                  </FieldRow>
                </FieldGroup>

                <FieldGroup title="Advanced">
                  <FieldRow label="Test mode">
                    <Toggle
                      checked={form.test_mode}
                      onChange={(v) => set("test_mode", v)}
                    />
                  </FieldRow>
                  <FieldRow
                    label="Install root"
                    hint="Override the default installation directory"
                  >
                    <TextInput
                      value={form.install_root}
                      onChange={(v) => set("install_root", v)}
                      placeholder="E:\GameServers\ARK"
                    />
                  </FieldRow>
                </FieldGroup>

                <FieldGroup title="Scheduling">
                  <FieldRow label="Scheduled update check">
                    <Toggle
                      checked={form.scheduled_update_check_enabled}
                      onChange={(v) => set("scheduled_update_check_enabled", v)}
                    />
                  </FieldRow>
                  <FieldRow label="Update check time" hint="HH:MM, 24-hour">
                    <TextInput
                      value={form.scheduled_update_check_time}
                      onChange={(v) => set("scheduled_update_check_time", v)}
                      placeholder="04:00"
                      disabled={!form.scheduled_update_check_enabled}
                    />
                  </FieldRow>
                  <FieldRow label="Auto-apply scheduled updates">
                    <Toggle
                      checked={form.scheduled_update_auto_apply}
                      onChange={(v) => set("scheduled_update_auto_apply", v)}
                    />
                  </FieldRow>
                  <FieldRow label="Scheduled restart">
                    <Toggle
                      checked={form.scheduled_restart_enabled}
                      onChange={(v) => set("scheduled_restart_enabled", v)}
                    />
                  </FieldRow>
                  <FieldRow label="Scheduled restart time" hint="HH:MM, 24-hour">
                    <TextInput
                      value={form.scheduled_restart_time}
                      onChange={(v) => set("scheduled_restart_time", v)}
                      placeholder="05:00"
                      disabled={!form.scheduled_restart_enabled}
                    />
                  </FieldRow>
                </FieldGroup>

                <FieldGroup title="Port Policy">
                  <FieldRow
                    label="Game port start"
                    hint="First port assigned for game traffic; leave blank to auto-assign"
                  >
                    <NumInput
                      value={form.default_game_port_start}
                      onChange={(v) => set("default_game_port_start", v)}
                      placeholder="30000"
                    />
                  </FieldRow>
                  <FieldRow
                    label="RCON port start"
                    hint="First port assigned for RCON; leave blank to auto-assign"
                  >
                    <NumInput
                      value={form.default_rcon_port_start}
                      onChange={(v) => set("default_rcon_port_start", v)}
                      placeholder="31000"
                    />
                  </FieldRow>
                </FieldGroup>

                <SaveRow
                  saving={saving}
                  success={success}
                  error={error}
                  onSave={handleSave}
                  label="Save Plugin Defaults"
                />
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Tab: Instance Config
// ─────────────────────────────────────────────────────────────────────────────

function InstanceConfigTab({
  instances,
  getToken,
  initialInstanceId,
}: {
  instances: Instance[];
  getToken: () => Promise<string | null>;
  initialInstanceId?: string | null;
}) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [form, setForm] = useState<InstanceForm>({ map: "", game_port: "", rcon_port: "", rcon_enabled: true, admin_password: "", max_players: "", server_name: "", mods: "", passive_mods: "", map_mod: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [applyNote, setApplyNote] = useState<string | null>(null);
  const requestedInstance = initialInstanceId
    ? instances.find((inst) => inst.instance_id === initialInstanceId) ?? null
    : null;
  const activeInstance = activeId
    ? instances.find((inst) => inst.instance_id === activeId) ?? null
    : null;

  const set = <K extends keyof InstanceForm>(k: K, v: InstanceForm[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  function selectInstance(inst: Instance) {
    setActiveId(inst.instance_id);
    setError(null);
    setSuccess(false);
    setApplyNote(null);
    setForm(instanceConfigToForm(inst.config_json ?? {}));
  }

  useEffect(() => {
    if (!initialInstanceId) return;
    const initialInstance = instances.find((inst) => inst.instance_id === initialInstanceId);
    if (!initialInstance) return;
    selectInstance(initialInstance);
  }, [initialInstanceId, instances]);

  useEffect(() => {
    if (initialInstanceId || activeId !== null || instances.length !== 1) return;
    selectInstance(instances[0]);
  }, [activeId, initialInstanceId, instances]);

  async function handleSave() {
    if (!activeId) return;
    const validErr = validateInstanceForm(form);
    if (validErr) { setError(validErr); return; }
    setSaving(true);
    setError(null);
    setSuccess(false);
    setApplyNote(null);
    try {
      const token = await getToken();
      const response: InstanceConfigSaveResponse = await saveInstanceConfig(
        token!,
        activeId,
        formToInstanceConfig(form),
      );
      setSuccess(true);
      const applyResult = response.apply_result;
      const applyData = applyResult?.data;
      if (applyResult?.status === "pending") {
        setApplyNote(applyData?.warnings?.[0] ?? "Saved. Host apply is pending.");
      } else if (applyResult?.status === "success" && applyData?.deferred) {
        setApplyNote(
          applyData?.warnings?.[0] ?? "Saved. Host apply is deferred until stop/start.",
        );
      } else if (applyResult?.status === "success" && applyData?.applied) {
        setApplyNote("Saved and applied on the host.");
      } else if (applyResult?.message) {
        setApplyNote(`Saved, but host apply failed: ${applyResult.message}`);
      }
      setTimeout(() => setSuccess(false), 3000);
    } catch (e: any) {
      setError(e.message ?? "Failed to save.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <p className="text-gray-500 text-sm mb-6">
        Per-server configuration. These values override plugin defaults for the
        selected server instance.
      </p>

      {requestedInstance && (
        <div className="mb-6 rounded-lg border border-blue-800 bg-blue-950/40 px-4 py-3">
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-xs uppercase tracking-wide text-blue-300">Managed Flow</div>
              <p className="mt-1 text-sm text-blue-100">
                Editing config for <span className="font-medium text-white">{requestedInstance.display_name}</span>.
              </p>
            </div>
            <Link
              href={`/instances/${encodeURIComponent(requestedInstance.instance_id)}`}
              className="shrink-0 text-sm text-blue-300 hover:text-white transition-colors"
            >
              Back to instance detail
            </Link>
          </div>
        </div>
      )}

      {initialInstanceId && !requestedInstance && instances.length > 0 && (
        <div className="mb-6 rounded-lg border border-yellow-800 bg-yellow-950/40 px-4 py-3 text-sm text-yellow-200">
          The requested instance could not be found. Select another server instance to continue.
        </div>
      )}

      {instances.length === 0 ? (
        <p className="text-gray-500 text-sm">No instances found.</p>
      ) : (
        <div className="flex gap-4">
          {/* Sidebar */}
          <div className="w-44 shrink-0 space-y-0.5">
            {instances.map((inst) => (
              <button
                key={inst.instance_id}
                onClick={() => selectInstance(inst)}
                className={`w-full text-left px-3 py-2 rounded transition-colors ${
                  activeId === inst.instance_id
                    ? "bg-gray-700 text-white"
                    : "text-gray-400 hover:bg-gray-800 hover:text-white"
                }`}
              >
                <span className="text-sm block truncate">{inst.display_name}</span>
                <span className="text-xs text-gray-600 font-mono">{inst.plugin_id}</span>
              </button>
            ))}
          </div>

          {/* Form panel */}
          <div className="flex-1 bg-gray-900 rounded-lg border border-gray-800 p-5">
            {activeId === null ? (
              <p className="text-gray-500 text-sm">
                Select a server instance to edit its configuration.
              </p>
            ) : (
              <>
                {activeInstance && (
                  <div className="mb-4 text-sm text-gray-400">
                    Editing <span className="text-white font-medium">{activeInstance.display_name}</span>
                    <span className="text-gray-600"> · {activeInstance.plugin_id}</span>
                  </div>
                )}
                <FieldGroup title="Identity">
                  <FieldRow label="Map" hint="Read-only — set when the server was created">
                    <TextInput value={form.map} disabled />
                  </FieldRow>
                  <FieldRow label="Server name" hint="Shown in the in-game server browser">
                    <TextInput
                      value={form.server_name}
                      onChange={(v) => set("server_name", v)}
                      placeholder="My ARK Server"
                    />
                  </FieldRow>
                </FieldGroup>

                <FieldGroup title="Network">
                  <FieldRow label="Game port" hint="UDP, default 7777">
                    <NumInput
                      value={form.game_port}
                      onChange={(v) => set("game_port", v)}
                      placeholder="7777"
                    />
                  </FieldRow>
                  <FieldRow label="RCON port" hint="TCP, default 27020">
                    <NumInput
                      value={form.rcon_port}
                      onChange={(v) => set("rcon_port", v)}
                      placeholder="27020"
                    />
                  </FieldRow>
                  <FieldRow label="RCON enabled">
                    <Toggle
                      checked={form.rcon_enabled}
                      onChange={(v) => set("rcon_enabled", v)}
                    />
                  </FieldRow>
                </FieldGroup>

                <FieldGroup title="Server">
                  <FieldRow label="Admin password">
                    <TextInput
                      value={form.admin_password}
                      onChange={(v) => set("admin_password", v)}
                      type="password"
                      placeholder="••••••••"
                    />
                  </FieldRow>
                  <FieldRow label="Max players" hint="1 – 65535">
                    <NumInput
                      value={form.max_players}
                      onChange={(v) => set("max_players", v)}
                      placeholder="20"
                    />
                  </FieldRow>
                </FieldGroup>

                <FieldGroup title="Mods">
                  <FieldRow label="Active mods" hint="One mod ID per line; prepended to plugin defaults">
                    <ModsArea
                      value={form.mods}
                      onChange={(v) => set("mods", v)}
                      placeholder={"927090\n895711"}
                    />
                  </FieldRow>
                  <FieldRow label="Passive mods" hint="One mod ID per line">
                    <ModsArea
                      value={form.passive_mods}
                      onChange={(v) => set("passive_mods", v)}
                    />
                  </FieldRow>
                  <FieldRow label="Map mod" hint="Mod ID that provides the custom map, if any">
                    <TextInput
                      value={form.map_mod}
                      onChange={(v) => set("map_mod", v)}
                      placeholder="928988"
                    />
                  </FieldRow>
                </FieldGroup>

                <SaveRow
                  saving={saving}
                  success={success}
                  error={error}
                  onSave={handleSave}
                  label="Save Instance Config"
                />
                {applyNote && (
                  <div className="mt-3 text-sm text-gray-400">{applyNote}</div>
                )}
                {success && activeInstance && (
                  <div className="mt-3 text-sm">
                    <Link
                      href={`/instances/${encodeURIComponent(activeInstance.instance_id)}`}
                      className="text-blue-300 hover:text-white transition-colors"
                    >
                      Return to instance detail
                    </Link>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Page
// ─────────────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const { getToken } = useAuth();
  const searchParams = useSearchParams();

  const [tab, setTab] = useState<Tab>("app");
  const [loading, setLoading] = useState(true);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const [appSettingsJson, setAppSettingsJson] = useState<Record<string, unknown>>({});
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [instances, setInstances] = useState<Instance[]>([]);

  const loadAll = useCallback(async () => {
    try {
      const token = await getToken();
      const [appData, pluginList, instanceList] = await Promise.all([
        fetchAppSettings(token!),
        fetchPlugins(token!),
        fetchInstances(token!),
      ]);
      setAppSettingsJson(appData.settings_json ?? {});
      setPlugins(pluginList);
      setInstances(instanceList);
    } catch (e: any) {
      setGlobalError(e.message ?? "Failed to load settings.");
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    const requestedTab = searchParams.get("tab");
    if (requestedTab === "app" || requestedTab === "plugins" || requestedTab === "instances") {
      setTab(requestedTab);
    }
  }, [searchParams]);

  const TABS: { id: Tab; label: string }[] = [
    { id: "app", label: "App Settings" },
    { id: "plugins", label: "Plugin Defaults" },
    { id: "instances", label: "Instance Config" },
  ];

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
          <Link href="/instances" className="text-sm text-gray-400 hover:text-white transition-colors">
            Instances
          </Link>
          <span className="text-sm text-white font-medium">Settings</span>
          <UserButton />
        </div>
      </nav>

      <main className="px-6 py-8 max-w-5xl">
        <h1 className="text-2xl font-bold mb-6">Settings</h1>

        {globalError && (
          <div className="mb-6 px-4 py-3 rounded bg-red-950 border border-red-800 text-red-300 text-sm">
            {globalError}
          </div>
        )}

        {loading ? (
          <div className="text-gray-500 text-sm py-16 text-center">Loading settings…</div>
        ) : (
          <>
            {/* Tab bar */}
            <div className="flex gap-1 mb-6 border-b border-gray-800 pb-0">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
                    tab === t.id
                      ? "border-blue-500 text-white"
                      : "border-transparent text-gray-400 hover:text-white"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* Tab content */}
            {tab === "app" && (
              <AppSettingsTab
                initial={appSettingsJson}
                onSaved={setAppSettingsJson}
                getToken={getToken}
              />
            )}
            {tab === "plugins" && (
              <PluginDefaultsTab plugins={plugins} getToken={getToken} />
            )}
            {tab === "instances" && (
              <InstanceConfigTab
                instances={instances}
                getToken={getToken}
                initialInstanceId={searchParams.get("instanceId")}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}
