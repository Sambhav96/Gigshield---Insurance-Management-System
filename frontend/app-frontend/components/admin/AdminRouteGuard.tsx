/**
 * AdminRouteGuard.tsx
 *
 * BUG-3 FIX: Now uses authService.verifyAdminSession() which reads from
 * gs_admin_token (not gs_rider_token). This ensures admin sessions are
 * fully isolated from rider sessions in the same browser.
 */
"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { authService } from "@/lib/api/auth";

type GuardState = "verifying" | "pass" | "redirect";

export function AdminRouteGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<GuardState>("verifying");

  useEffect(() => {
    let mounted = true;

    async function verify() {
      setState("verifying");
      // BUG-3 FIX: use admin-scoped session check
      const sessionRes = await authService.verifyAdminSession();

      if (!sessionRes.data?.user) {
        if (mounted) {
          router.replace("/login/admin");
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
      <div className="fixed inset-0 z-[999] bg-[var(--color-admin-bg)] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <span className="material-symbols-outlined animate-spin text-[var(--color-admin-primary)] text-4xl">
            autorenew
          </span>
          <p className="text-[var(--color-admin-outline)] text-[10px] font-['JetBrains_Mono'] uppercase tracking-widest">
            Authenticating...
          </p>
        </div>
      </div>
    );
  }

  if (state === "redirect") return null;
  return <>{children}</>;
}
