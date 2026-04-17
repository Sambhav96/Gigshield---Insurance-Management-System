"use client";

import { RiderPageTransition } from "@/lib/motion/safeWrappers";
import { motion, Variants } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { fetchApi, riderPath } from "@/lib/api/client";
import { ClaimResponse, LiveDashboardResponse } from "@/lib/api/types";

type PayoutRecord = ClaimResponse & {
  payout_type?: string;
  released_at?: string;
  claim_reference?: string;
  reference?: string;
  amount?: number;
  razorpay_status?: string;
};

function normalizePayoutsPayload(payload: unknown): { list: PayoutRecord[]; availableBalance?: number } {
  if (Array.isArray(payload)) {
    return { list: payload as PayoutRecord[] };
  }

  if (!payload || typeof payload !== "object") {
    return { list: [] };
  }

  const wrapped = payload as {
    payouts?: unknown;
    items?: unknown;
    data?: unknown;
    available_balance?: unknown;
  };

  const list = Array.isArray(wrapped.payouts)
    ? (wrapped.payouts as PayoutRecord[])
    : Array.isArray(wrapped.items)
      ? (wrapped.items as PayoutRecord[])
      : Array.isArray(wrapped.data)
        ? (wrapped.data as PayoutRecord[])
        : [];

  const availableBalance =
    typeof wrapped.available_balance === "number"
      ? wrapped.available_balance
      : undefined;

  return { list, availableBalance };
}

export default function EarningsPage() {
  const [payouts, setPayouts] = useState<PayoutRecord[] | null>(null);
  const [availableBalance, setAvailableBalance] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [liveDashboard, setLiveDashboard] = useState<LiveDashboardResponse | null>(null);

  useEffect(() => {
    let mounted = true;

    async function load() {
      setIsLoading(true);
      setError(null);

      const [payoutsRes, liveRes] = await Promise.all([
        fetchApi<unknown>(riderPath("/riders/me/payouts"), { method: "GET" }),
        fetchApi<LiveDashboardResponse>(riderPath("/dashboard/live"), { method: "GET" }),
      ]);

      if (!mounted) return;

      if (!liveRes.error && liveRes.data) {
        setLiveDashboard(liveRes.data);
      }

      if (payoutsRes.status === 404 || payoutsRes.status === 501) {
        setPayouts([]);
        setAvailableBalance(0);
        setIsLoading(false);
        return;
      }

      if (payoutsRes.error || !payoutsRes.data) {
        setError(payoutsRes.error?.message || "Unable to load settlements");
        setPayouts([]);
        setAvailableBalance(0);
        setIsLoading(false);
        return;
      }

      const { list, availableBalance: availableFromApi } = normalizePayoutsPayload(payoutsRes.data);
      setPayouts(list);

      const computedTotal = list
        .filter((p) => {
          const payoutType = String(p?.payout_type || "");
          const status = String((p as any)?.status || p?.razorpay_status || "").toLowerCase();
          return payoutType !== "premium_debit" && (status === "released" || status === "success" || status === "paid" || status === "");
        })
        .reduce((sum, p) => sum + Number(p?.actual_payout ?? p?.amount ?? 0), 0);

      setAvailableBalance(Number(availableFromApi ?? computedTotal));
      setIsLoading(false);
    }

    load();
    return () => {
      mounted = false;
    };
  }, []);

  const settlements = useMemo(() => {
    const list = Array.isArray(payouts) ? payouts : [];
    return list.filter((p) => String(p?.payout_type || "") !== "premium_debit");
  }, [payouts]);

  const itemVariants: Variants = {
    hidden: { opacity: 0, y: 10 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.3 } }
  };

  return (
    <RiderPageTransition>
      <motion.div initial="hidden" animate="visible" transition={{ staggerChildren: 0.1 }} className="space-y-6">
        {error && (
          <motion.div variants={itemVariants} className="bg-[var(--color-rider-error)]/20 border border-[var(--color-rider-error)] text-[var(--color-rider-error)] text-xs font-['Manrope'] font-medium px-4 py-3 rounded-xl flex items-center gap-2">
            <span className="material-symbols-outlined text-sm">error</span>
            {error}
          </motion.div>
        )}

        {isLoading && (
          <motion.div variants={itemVariants} className="fixed inset-0 z-[999] bg-[var(--color-rider-bg)] flex items-center justify-center">
            <div className="flex flex-col items-center gap-4">
              <span className="material-symbols-outlined animate-spin text-[var(--color-rider-primary)] text-4xl">autorenew</span>
              <p className="text-white/30 text-xs font-['Manrope'] tracking-widest uppercase">Loading earnings</p>
            </div>
          </motion.div>
        )}
        
        <motion.div variants={itemVariants} className="text-center pt-4">
          <p className="text-[#a8abb3] text-sm font-['Manrope'] mb-1">Available for Payout</p>
          <h1 className="text-5xl font-['Space_Grotesk'] font-bold text-white mb-6 tracking-tighter">₹{availableBalance.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</h1>
          
          <button className="bg-[var(--color-rider-primary)] text-[#002635] px-8 py-3.5 rounded-full font-bold font-['Space_Grotesk'] text-lg shadow-[0_0_20px_rgba(84,199,252,0.3)] active:scale-95 transition-transform w-full">
            View Settlement History
          </button>
        </motion.div>

        {/* Protection Multiplier */}
        <motion.div variants={itemVariants} className="rider-glass-card rounded-2xl p-5 flex items-center gap-4 mt-8">
          <div className="w-12 h-12 rounded-full bg-[var(--color-rider-secondary)]/10 flex items-center justify-center flex-shrink-0">
            <span className="material-symbols-outlined text-[var(--color-rider-secondary)]">bolt</span>
          </div>
          <div>
            <h3 className="text-white font-bold text-sm">Active Multiplier: {liveDashboard?.mu_label || "No active trigger"}</h3>
            <p className="text-[#a8abb3] text-xs">{liveDashboard?.active_trigger ? "Live trigger detected in your zone." : "No active trigger currently."}</p>
          </div>
        </motion.div>

        {/* Recent Activity Mini */}
        <motion.div variants={itemVariants} className="pt-4 space-y-4">
          <h3 className="text-xs font-bold uppercase tracking-[0.2em] text-[#a8abb3] pl-1">Recent Settlements</h3>

          {settlements.length === 0 ? (
            <div className="flex justify-between items-center bg-white/[0.02] border border-white/5 rounded-xl p-4">
              <div className="flex items-center gap-3">
                <div className="bg-[#1b2028] p-2 rounded-lg text-white">
                  <span className="material-symbols-outlined text-sm">schedule</span>
                </div>
                <div>
                  <p className="text-sm font-bold text-white">No settlements yet</p>
                  <p className="text-xs text-[#a8abb3]">Payouts will appear here automatically.</p>
                </div>
              </div>
              <p className="text-white/40 font-['Space_Grotesk'] font-bold">₹0.00</p>
            </div>
          ) : (
            settlements.map((p, idx) => {
              const dt = p.released_at || p.initiated_at;
              const dateLabel = dt ? new Date(dt).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "Settlement record";
              const payoutId = String(p?.id || `payout-${idx}`);
              const title = p.reference || p.claim_reference || `Claim ${payoutId.slice(0, 8)}`;
              const amount = Number(p?.actual_payout ?? p?.amount ?? 0);
              const sign = amount >= 0 ? "+" : "";

              return (
                <div key={payoutId} className="flex justify-between items-center bg-white/[0.02] border border-white/5 rounded-xl p-4">
                  <div className="flex items-center gap-3">
                    <div className="bg-[#1b2028] p-2 rounded-lg text-white">
                      <span className="material-symbols-outlined text-sm">check_circle</span>
                    </div>
                    <div>
                      <p className="text-sm font-bold text-white">{title}</p>
                      <p className="text-xs text-[#a8abb3]">{dateLabel}</p>
                    </div>
                  </div>
                  <p className="text-[var(--color-rider-secondary)] font-['Space_Grotesk'] font-bold">{sign}₹{Math.abs(amount).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
                </div>
              );
            })
          )}
        </motion.div>

      </motion.div>
    </RiderPageTransition>
  );
}
