/**
 * HubRouteGuard.tsx — Fixed to use hub-scoped token (gs_hub_token)
 */
"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { authService } from "@/lib/api/auth";

type GuardState = "verifying" | "pass" | "redirect";

export function HubRouteGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<GuardState>("verifying");

  useEffect(() => {
    let mounted = true;

    async function verify() {
      setState("verifying");
      const sessionRes = await authService.verifyHubSession();

      if (!sessionRes.data?.user) {
        if (mounted) {
          router.replace("/login/hub-manager");
          setState("redirect");
        }
        return;
      }

      if (mounted) setState("pass");
    }

    verify();
    return () => { mounted = false; };
  }, [pathname, router]);

  if (state === "verifying") {
    return (
      <div className="fixed inset-0 z-[999] bg-[var(--color-hub-bg)] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <span className="material-symbols-outlined animate-spin text-[var(--color-hub-secondary)] text-4xl">
            autorenew
          </span>
          <p className="text-white/30 text-xs font-['DM_Sans'] uppercase tracking-widest">
            Authenticating...
          </p>
        </div>
      </div>
    );
  }

  if (state === "redirect") return null;
  return <>{children}</>;
}
