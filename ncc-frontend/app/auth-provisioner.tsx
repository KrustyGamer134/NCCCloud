"use client";

import { useAuth } from "@clerk/nextjs";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.krustystudios.com";
const ONBOARDING_PATH = "/onboarding";

/**
 * Calls POST /auth/provision once whenever the user is signed in.
 * This creates the tenant + user row in the backend DB on first login,
 * and is idempotent for existing users (returns early with existing data).
 * Renders nothing — purely a side-effect component.
 */
export default function AuthProvisioner() {
  const { isSignedIn, getToken } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!isSignedIn) return;
    (async () => {
      try {
        const token = await getToken();
        if (!token) return;
        await fetch(`${API_URL}/auth/provision`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });

        const settingsResponse = await fetch(`${API_URL}/settings/app`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!settingsResponse.ok) return;

        const settingsPayload = await settingsResponse.json();
        const settings =
          settingsPayload && typeof settingsPayload.settings_json === "object"
            ? settingsPayload.settings_json
            : {};
        const gameserversRoot = String(settings?.gameservers_root ?? "").trim();
        const onAuthPage =
          pathname === "/sign-in" ||
          pathname === "/sign-up" ||
          pathname?.startsWith("/sign-in/") ||
          pathname?.startsWith("/sign-up/");
        const onOnboardingPage =
          pathname === ONBOARDING_PATH ||
          pathname?.startsWith(`${ONBOARDING_PATH}/`);

        if (!gameserversRoot && !onOnboardingPage) {
          router.replace(ONBOARDING_PATH);
          return;
        }

        if (gameserversRoot && (onAuthPage || onOnboardingPage)) {
          router.replace("/dashboard");
        }
      } catch {
        // Non-fatal: the user will see 403s on data fetches until provision
        // succeeds, which will happen on the next navigation or refresh.
      }
    })();
  }, [isSignedIn, getToken, pathname, router]);

  return null;
}
