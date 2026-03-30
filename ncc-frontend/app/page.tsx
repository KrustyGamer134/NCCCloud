import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import Link from "next/link";

export default async function LandingPage() {
  const { userId } = await auth();
  if (userId) {
    redirect("/dashboard");
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <nav className="border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-xl font-bold text-white">NCC</span>
          <span className="text-gray-500 text-sm">Game Server Manager</span>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/sign-in"
            className="text-sm text-gray-300 hover:text-white transition-colors"
          >
            Log In
          </Link>
          <Link
            href="/sign-up"
            className="rounded border border-blue-500 bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500"
          >
            Create Account
          </Link>
        </div>
      </nav>
      <main className="mx-auto flex min-h-[calc(100vh-73px)] max-w-5xl items-center px-6 py-16">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-blue-300">
            Deterministic Game Server Control
          </p>
          <h1 className="mt-4 text-5xl font-bold tracking-tight text-white">
            Manage game servers from one control surface.
          </h1>
          <p className="mt-6 max-w-2xl text-lg text-gray-400">
            NCC keeps runtime actions, installs, and host state routed through a
            single system so server management stays predictable.
          </p>
          <div className="mt-10 flex flex-wrap gap-4">
            <Link
              href="/sign-up"
              className="rounded border border-blue-500 bg-blue-600 px-5 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-500"
            >
              Create Account
            </Link>
            <Link
              href="/sign-in"
              className="rounded border border-gray-700 px-5 py-3 text-sm font-medium text-gray-200 transition-colors hover:border-gray-500 hover:text-white"
            >
              Log In
            </Link>
            <Link
              href="/dashboard"
              className="rounded border border-gray-800 px-5 py-3 text-sm font-medium text-gray-500 transition-colors hover:border-gray-600 hover:text-gray-300"
            >
              Open Dashboard
            </Link>
          </div>
        </div>
      </main>
    </div>
  );
}
