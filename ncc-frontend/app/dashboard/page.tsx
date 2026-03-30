import { UserButton } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { redirect } from "next/navigation";
import { fetchAgents, fetchAppSettings, fetchInstances } from "../lib/api";

export default async function DashboardPage() {
  const { getToken } = await auth();
  const token = await getToken();

  try {
    const appSettings = await fetchAppSettings(token!);
    const gameserversRoot = String(appSettings?.settings_json?.gameservers_root ?? "").trim();
    if (!gameserversRoot) {
      redirect("/onboarding");
    }
  } catch {}

  let agents = [];
  let instances = [];

  try {
    agents = await fetchAgents(token!);
  } catch {}

  try {
    instances = await fetchInstances(token!);
  } catch {}

  const onlineAgents = agents.filter((a: any) => a.is_connected === true).length;
  const totalInstances = instances.length;
  const runningInstances = instances.filter((i: any) => i.status === "running").length;

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <nav className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold text-white">NCC</span>
          <span className="text-gray-500 text-sm">Game Server Manager</span>
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
      <main className="px-6 py-8">
        <h1 className="text-2xl font-bold mb-6">Dashboard</h1>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
            <p className="text-gray-400 text-sm">Agents Online</p>
            <p className="text-3xl font-bold mt-1">{onlineAgents}</p>
          </div>
          <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
            <p className="text-gray-400 text-sm">Game Servers</p>
            <p className="text-3xl font-bold mt-1">{totalInstances}</p>
          </div>
          <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
            <p className="text-gray-400 text-sm">Running Servers</p>
            <p className="text-3xl font-bold mt-1">{runningInstances}</p>
          </div>
        </div>
      </main>
    </div>
  );
}
