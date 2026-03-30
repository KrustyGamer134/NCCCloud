"use client";

import { useAuth, UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchAppSettings, saveAppSettings } from "../lib/api";

export default function OnboardingPage() {
  const { getToken } = useAuth();
  const router = useRouter();
  const [gameserversRoot, setGameserversRoot] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const token = await getToken();
        if (!token) return;
        const response = await fetchAppSettings(token);
        const existingRoot = String(response?.settings_json?.gameservers_root ?? "").trim();
        if (cancelled) return;
        if (existingRoot) {
          router.replace("/dashboard");
          return;
        }
        setGameserversRoot(existingRoot);
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.message ?? "Failed to load onboarding settings.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [getToken, router]);

  async function handleContinue() {
    const trimmedRoot = gameserversRoot.trim();
    if (!trimmedRoot) {
      setError("Top-level install location is required.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const token = await getToken();
      if (!token) {
        throw new Error("Authentication is required.");
      }

      await saveAppSettings(token, { gameservers_root: trimmedRoot });
      router.replace("/dashboard");
    } catch (e: any) {
      setError(e?.message ?? "Failed to save onboarding settings.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <nav className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link href="/" className="text-xl font-bold text-white hover:text-gray-300">
            NCC
          </Link>
          <span className="text-gray-500 text-sm">Game Server Manager</span>
        </div>
        <UserButton />
      </nav>

      <main className="mx-auto flex min-h-[calc(100vh-73px)] max-w-3xl items-center px-6 py-16">
        <div className="w-full rounded-2xl border border-gray-800 bg-gray-900/80 p-8 shadow-2xl">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-blue-300">
            First-Time Setup
          </p>
          <h1 className="mt-4 text-4xl font-bold tracking-tight text-white">
            Choose where this machine will keep server installs.
          </h1>
          <p className="mt-4 max-w-2xl text-base text-gray-400">
            Start with the top-level location only. You can fill in SteamCMD and the rest of
            the host settings later from the app.
          </p>

          <div className="mt-10">
            <label className="block text-sm font-medium text-gray-200" htmlFor="gameservers-root">
              Top-level install location
            </label>
            <input
              id="gameservers-root"
              type="text"
              value={gameserversRoot}
              onChange={(e) => setGameserversRoot(e.target.value)}
              placeholder="E:\\GameServers"
              disabled={loading || saving}
              className="mt-3 w-full rounded border border-gray-700 bg-gray-950 px-4 py-3 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-gray-500 disabled:cursor-not-allowed disabled:opacity-60"
            />
            <p className="mt-2 text-sm text-gray-500">
              Example: <span className="font-mono">D:\Ark</span> or{" "}
              <span className="font-mono">E:\GameServers</span>
            </p>
          </div>

          {error && (
            <div className="mt-6 rounded border border-red-800 bg-red-950/40 px-4 py-3 text-sm text-red-200">
              {error}
            </div>
          )}

          <div className="mt-8 flex items-center gap-4">
            <button
              type="button"
              onClick={handleContinue}
              disabled={loading || saving}
              className="rounded border border-blue-500 bg-blue-600 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? "Saving..." : "Continue"}
            </button>
            <span className="text-sm text-gray-500">
              {loading ? "Checking host settings..." : "You can adjust the rest later in Settings."}
            </span>
          </div>
        </div>
      </main>
    </div>
  );
}
