"use client";

import { RiderPageTransition } from "@/lib/motion/safeWrappers";
import { motion, Variants } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { fetchApi, riderPath } from "@/lib/api/client";
import { subscribeToRiderClaims, subscribeToRiderPayouts, subscribeToTriggerEvents } from "@/lib/api/realtime";
import { LiveDashboardResponse, PolicyResponse, RiderProfileResponse } from "@/lib/api/types";
import { adaptLiveDashboard, adaptPolicyResponse } from "@/lib/api/adapters";

const TRIGGER_LABELS: Record<string, string> = {
  rain: "Heavy Rain Alert",
  aqi: "AQI Alert",
  flood: "Flood Alert",
  heat: "Heat Wave Alert",
  bandh: "Bandh Alert",
  platform: "Platform Outage",
};

type OracleTelemetry = {
  aqi?: number | string;
  precipitation?: number | string;
  storm_cell?: number | string;
  storm?: number | string;
};

export default function RiderHome() {
  const [liveDashboard, setLiveDashboard] = useState<LiveDashboardResponse | null>(null);
  const [policy, setPolicy] = useState<PolicyResponse | null>(null);
  const [rider, setRider] = useState<RiderProfileResponse | null>(null);
  const [oracle, setOracle] = useState<OracleTelemetry | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [oracleLoading, setOracleLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function load() {
      setIsLoading(true);
      setError(null);

      const [liveRes, policyRes, riderRes, oracleRes] = await Promise.all([
        fetchApi<LiveDashboardResponse>(riderPath("/dashboard/live"), { method: "GET" }),
        fetchApi<PolicyResponse>(riderPath("/policies/me"), { method: "GET" }),
        fetchApi<RiderProfileResponse>(riderPath("/riders/me"), { method: "GET" }),
        fetchApi<OracleTelemetry>(riderPath("/telemetry/latest-zone"), { method: "GET" }),
      ]);

      if (!mounted) return;

      if (liveRes.error || !liveRes.data || policyRes.error || !policyRes.data || riderRes.error || !riderRes.data) {
        setError((liveRes.error || policyRes.error || riderRes.error)?.message || "Unable to load dashboard data.");
      } else {
        setLiveDashboard(liveRes.data);
        setPolicy(policyRes.data);
        setRider(riderRes.data);
      }

      if (!oracleRes.error && oracleRes.data) {
        setOracle(oracleRes.data);
      }
      setOracleLoading(false);
      setIsLoading(false);
    }

    load();

    // Real-time polling every 30s as fallback
    const pollInterval = setInterval(() => {
      if (document.visibilityState === "visible") {
        load();
      }
    }, 30000);

    // Supabase Realtime subscriptions (instant updates if configured)
    const riderId = typeof window !== "undefined" ? localStorage.getItem("gs_rider_id") : null;
    const unsubs: Array<() => void> = [];

    if (riderId) {
      // Instant payout notification
      unsubs.push(subscribeToRiderPayouts(riderId, () => {
        if (mounted) load();
      }));
      // Instant claim status update
      unsubs.push(subscribeToRiderClaims(riderId, () => {
        if (mounted) load();
      }));
    }

    return () => {
      mounted = false;
      clearInterval(pollInterval);
      unsubs.forEach(fn => fn());
    };
  }, []);

  const adaptedDashboard = useMemo(
    () => (liveDashboard ? adaptLiveDashboard(liveDashboard) : null),
    [liveDashboard]
  );

  const adaptedPolicy = useMemo(
    () => (policy ? adaptPolicyResponse(policy) : null),
    [policy]
  );

  const planLabel = useMemo(() => {
    const plan = (policy?.plan || "").toLowerCase();
    if (plan === "basic") return "Bronze Shield";
    if (plan === "pro") return "Gold Shield";
    return "Silver Shield";
  }, [policy?.plan]);

  const nextDebitDays = useMemo(() => {
    if (!adaptedDashboard?.nextDebit) return "--";
    const debitAt = new Date(adaptedDashboard.nextDebit);
    if (Number.isNaN(debitAt.getTime())) return "--";
    const ms = debitAt.getTime() - Date.now();
    return Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24))).toString();
  }, [adaptedDashboard?.nextDebit]);

  const weeklyCap = useMemo(() => {
    const income = Number(rider?.effective_income || 0);
    const multiplier = Number(adaptedPolicy?.capMultiplier || 0);
    return Math.max(0, Math.round(income * multiplier));
  }, [rider?.effective_income, adaptedPolicy?.capMultiplier]);

  const weeklyRemaining = Number(adaptedDashboard?.weeklyRemaining || 0);
  const earningsPct = weeklyCap > 0 ? Math.max(0, Math.min(100, (weeklyRemaining / weeklyCap) * 100)) : 0;

  const triggerType = (adaptedDashboard?.activeTrigger?.type || "").toLowerCase();
  const triggerLabel = TRIGGER_LABELS[triggerType] || "Alert";

  const oracleAqi = oracle?.aqi ?? "\u2014";
  const oraclePrecip = oracle?.precipitation ?? "\u2014";
  const oracleStorm = oracle?.storm_cell ?? oracle?.storm ?? "\u2014";

  const itemVariants: Variants = {
    hidden: { opacity: 0, y: 10 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.3 } }
  };

  if (isLoading) {
    return (
      <RiderPageTransition>
        <div className="fixed inset-0 z-[999] bg-[var(--color-rider-bg)] flex items-center justify-center">
          <div className="flex flex-col items-center gap-4">
            <span className="material-symbols-outlined animate-spin text-[var(--color-rider-primary)] text-4xl">autorenew</span>
            <p className="text-white/30 text-xs font-['Manrope'] tracking-widest uppercase">Loading dashboard</p>
          </div>
        </div>
      </RiderPageTransition>
    );
  }

  return (
    <RiderPageTransition>
      <motion.div 
        className="space-y-6"
        initial="hidden"
        animate="visible"
        transition={{ staggerChildren: 0.1 }}
      >
        {error && (
          <motion.div variants={itemVariants} className="bg-[var(--color-rider-error)]/20 border border-[var(--color-rider-error)] text-[var(--color-rider-error)] text-xs font-['Manrope'] font-medium px-4 py-3 rounded-xl flex items-center gap-2">
            <span className="material-symbols-outlined text-sm">error</span>
            {error}
          </motion.div>
        )}

        {/* Active Trigger Banner */}
        {adaptedDashboard?.activeTrigger && (
          <motion.div variants={itemVariants} className="w-full bg-[#9f0519]/20 border border-[var(--color-rider-error)]/20 rounded-xl p-4 flex items-center gap-4 overflow-hidden relative">
            <div className="absolute inset-0 bg-gradient-to-r from-[var(--color-rider-error)]/5 to-transparent pointer-events-none animate-pulse" />
            <div className="bg-[var(--color-rider-error)]/10 p-2 rounded-lg">
              <span className="material-symbols-outlined text-[var(--color-rider-error)]" style={{ fontVariationSettings: "'FILL' 1" }}>rainy_heavy</span>
            </div>
            <div className="flex-1 z-10">
              <h4 className="text-sm font-bold text-white">{triggerLabel}</h4>
              <p className="text-xs text-[#a8abb3]">Earnings protection multiplier {adaptedDashboard.muLabel} active.</p>
            </div>
            <span className="material-symbols-outlined text-[var(--color-rider-error)] animate-pulse z-10">sensors</span>
          </motion.div>
        )}

        {/* Silver Shield Card */}
        <motion.section variants={itemVariants} className="bg-[#0c141d] rounded-2xl p-6 border border-white/5 relative overflow-hidden shadow-2xl">
          <div className="flex justify-between items-start mb-10 relative z-10">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-white/60 text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>star</span>
                <h2 className="font-['Space_Grotesk'] text-2xl font-bold text-white tracking-tight">{planLabel}</h2>
              </div>
              <p className="text-white/40 text-sm font-medium">Expires in {nextDebitDays} days</p>
            </div>
            <div className="flex items-center gap-1.5 bg-[#0a231b] border border-[#164e3c] px-3 py-1 rounded-full">
              <div className="w-2 h-2 rounded-full bg-[#10b981]" />
              <span className="text-[10px] font-bold text-[#10b981] tracking-widest uppercase">{adaptedDashboard?.policyStatus || "Unknown"}</span>
            </div>
          </div>
          <div className="relative z-10 grid grid-cols-2 gap-8 items-end">
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-white/40">Coverage</p>
              <p className="text-2xl font-['Space_Grotesk'] font-bold text-white">₹{weeklyCap.toLocaleString("en-IN")}<span className="text-sm font-medium text-white/40 ml-1">/wk</span></p>
            </div>
            <div className="space-y-1.5 border-l border-white/10 pl-8">
              <p className="text-xs font-medium text-white/40">Premium</p>
              <p className="text-2xl font-['Space_Grotesk'] font-bold text-[var(--color-rider-primary)]">₹{Number(adaptedPolicy?.premiumAmount || 0).toLocaleString("en-IN")}<span className="text-sm font-medium text-white/40 ml-1">/wk</span></p>
            </div>
          </div>
          {/* Background Illustration */}
          <div className="absolute -right-6 -bottom-10 opacity-[0.03] pointer-events-none">
            <svg fill="currentColor" height="200" viewBox="0 0 24 24" width="200" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 1L3 5V11C3 16.55 6.84 21.74 12 23C17.16 21.74 21 16.55 21 11V5L12 1Z" />
            </svg>
          </div>
        </motion.section>

        {/* Live Oracle Strip */}
        <motion.section variants={itemVariants} className="space-y-3">
          <h3 className="text-xs font-bold uppercase tracking-[0.2em] text-[#a8abb3] pl-1">Risks</h3>
          <div className="flex gap-4 overflow-x-auto pb-2 scrollbar-hide no-scrollbar -mx-4 px-4">
            <div className="flex-none w-40 rider-glass-card p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="material-symbols-outlined text-[var(--color-rider-primary)] text-xl">air</span>
                <span className="text-[10px] font-bold text-[#a8abb3]">AQI</span>
              </div>
              <p className="text-2xl font-['Space_Grotesk'] font-bold text-white">{oracleAqi}</p>
              <p className="text-[10px] font-medium text-[var(--color-rider-secondary)]">{oracleLoading || !oracle ? "Loading oracle..." : "Latest zone telemetry"}</p>
            </div>
            <div className="flex-none w-40 rider-glass-card border-l-4 border-l-[var(--color-rider-primary)]/30 p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="material-symbols-outlined text-[#2eacdf] text-xl">water_drop</span>
                <span className="text-[10px] font-bold text-[#a8abb3]">Precipitation</span>
              </div>
              <p className="text-2xl font-['Space_Grotesk'] font-bold text-white">{oraclePrecip}</p>
              <p className="text-[10px] font-medium text-[#a8abb3]">{oracleLoading || !oracle ? "Loading oracle..." : "Latest zone telemetry"}</p>
            </div>
            <div className="flex-none w-40 rider-glass-card p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="material-symbols-outlined text-[#ffe792] text-xl">thunderstorm</span>
                <span className="text-[10px] font-bold text-[#a8abb3]">Storm Cell</span>
              </div>
              <p className="text-2xl font-['Space_Grotesk'] font-bold text-white">{oracleStorm}</p>
              <p className="text-[10px] font-medium text-[#a8abb3]">{oracleLoading || !oracle ? "Loading oracle..." : "Latest zone telemetry"}</p>
            </div>
          </div>
        </motion.section>

        {/* Earnings Protection Bar */}
        <motion.section variants={itemVariants} className="rider-glass-card p-6 border-t-2 border-t-[var(--color-rider-secondary)]/20">
          <div className="flex justify-between items-end mb-4">
            <div>
              <span className="block text-[10px] font-bold uppercase tracking-widest text-[#a8abb3] opacity-60">Earnings Protected</span>
              <h3 className="text-2xl font-['Space_Grotesk'] font-extrabold text-white">₹{weeklyRemaining.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</h3>
            </div>
          </div>
          <div className="h-4 w-full bg-[#151a21] rounded-full overflow-hidden p-1 border border-white/5">
            <div className="h-full bg-gradient-to-r from-[#025e16] to-[var(--color-rider-secondary)] rounded-full shadow-[0_0_15px_rgba(157,241,151,0.3)]" style={{ width: `${earningsPct}%` }} />
          </div>
          <div className="flex justify-between mt-2">
            <span className="text-[10px] font-bold text-[var(--color-rider-secondary)]">Target: ₹{weeklyCap.toLocaleString("en-IN")}</span>
            <span className="text-[10px] font-bold text-[var(--color-rider-secondary)]">{Math.round(earningsPct)}%</span>
          </div>
        </motion.section>

      </motion.div>
    </RiderPageTransition>
  );
}
