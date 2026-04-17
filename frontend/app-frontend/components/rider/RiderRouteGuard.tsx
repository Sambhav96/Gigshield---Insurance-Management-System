/**
 * RiderRouteGuard.tsx
 *
 * BUG-2 FIX: Removed fragile gs_fund_account_id localStorage check.
 * Onboarding completion is now determined purely from backend state:
 *   1. Does /riders/me return a profile with hub_id?  → show payout step
 *   2. Does /policies/me return an active policy?     → rider is fully onboarded
 * This eliminates the infinite redirect loop after enrollment.
 */
"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { authService } from "@/lib/api/auth";
import { fetchApi, riderPath } from "@/lib/api/client";
import { PolicyResponse, RiderProfileResponse } from "@/lib/api/types";

type GuardState = "verifying" | "pass" | "redirect";
const ONBOARDING_REQUIRED_KEY = "gs_onboarding_required";

export function RiderRouteGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [state, setState] = useState<GuardState>("verifying");

  useEffect(() => {
    let mounted = true;

    async function verify() {
      setState("verifying");

      // 1. Check rider-scoped session (uses gs_rider_token only)
      const sessionRes = await authService.verifyRiderSession();
      if (!sessionRes.data?.user) {
        if (mounted) { router.replace("/login/rider"); setState("redirect"); }
        return;
      }

      // 2. Only run onboarding gate on /rider/* routes for newly registered riders.
      if (pathname.startsWith("/rider")) {
        const requireOnboarding =
          typeof window !== "undefined" &&
          localStorage.getItem(ONBOARDING_REQUIRED_KEY) === "1";

        if (!requireOnboarding) {
          if (mounted) setState("pass");
          return;
        }

        try {
          // Check backend profile
          const profileRes = await fetchApi<RiderProfileResponse>(riderPath("/riders/me"));

          if (profileRes.status === 401) {
            authService.logout();
            if (mounted) { router.replace("/login/rider"); setState("redirect"); }
            return;
          }

          // No profile or no hub_id → send to profile step
          if (profileRes.error || !profileRes.data) {
            if (mounted) { router.replace("/onboarding/rider?step=profile"); setState("redirect"); }
            return;
          }

          const riderData = profileRes.data as any;
          const resolvedHubId =
            riderData.hub_id ||
            (typeof window !== "undefined" ? localStorage.getItem("gs_hub_id") : "") ||
            "";

          if (!resolvedHubId) {
            if (mounted) { router.replace("/onboarding/rider?step=profile"); setState("redirect"); }
            return;
          }

          // Check if payout destination is set (from backend, not localStorage)
          if (!riderData.razorpay_fund_account_id) {
            if (mounted) { router.replace("/onboarding/rider?step=payout"); setState("redirect"); }
            return;
          }

          // Check active policy
          const policyRes = await fetchApi<PolicyResponse>(riderPath("/policies/me"));
          if (
            policyRes.status === 404 ||
            policyRes.error ||
            !policyRes.data ||
            policyRes.data.status !== "active"
          ) {
            if (mounted) { router.replace("/onboarding/rider?step=policy"); setState("redirect"); }
            return;
          }

          // Fully onboarded in backend; clear one-time onboarding flag.
          if (typeof window !== "undefined") {
            localStorage.removeItem(ONBOARDING_REQUIRED_KEY);
          }
        } catch {
          // Network failure: allow pass-through so dashboard error states handle it
        }
      }

      // 3. All checks passed
      if (mounted) setState("pass");
    }

    verify();
    return () => { mounted = false; };
  }, [pathname, router]);

  if (state === "verifying") {
    return (
      <div className="fixed inset-0 z-[999] bg-[var(--color-rider-bg)] flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <span className="material-symbols-outlined animate-spin text-[var(--color-rider-primary)] text-4xl">
            autorenew
          </span>
          <p className="text-white/30 text-xs font-['Manrope'] tracking-widest uppercase">
            Verifying session
          </p>
        </div>
      </div>
    );
  }

  if (state === "redirect") return null;
  return <>{children}</>;
}
