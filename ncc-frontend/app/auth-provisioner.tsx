"use client";

import { useAuth } from "@clerk/nextjs";
import { useEffect } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://api.krustystudios.com";

/**
 * Calls POST /auth/provision once whenever the user is signed in.
 * This creates the tenant + user row in the backend DB on first login,
 * and is idempotent for existing users (returns early with existing data).
 * Renders nothing — purely a side-effect component.
 */
export default function AuthProvisioner() {
  const { isSignedIn, getToken } = useAuth();

  useEffect(() => {
    if (!isSignedIn) return;
    (async () => {
      try {
        const token = await getToken();
        await fetch(`${API_URL}/auth/provision`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
      } catch {
        // Non-fatal: the user will see 403s on data fetches until provision
        // succeeds, which will happen on the next navigation or refresh.
      }
    })();
  }, [isSignedIn, getToken]);

  return null;
}
