"use client";

import { HubPageCrossfade } from "@/lib/motion/safeWrappers";
import { useEffect, useState } from "react";
import { fetchApi, riderPath, hubPath } from "@/lib/api/client";
import { HubMetricsResponse } from "@/lib/api/types";

export default function HubDashboard() {
  const [metrics, setMetrics] = useState<HubMetricsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [oracleMessage, setOracleMessage] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function load() {
      setIsLoading(true);
      setError(null);

      const res = await fetchApi<HubMetricsResponse>(hubPath("/hub/metrics"), { method: "GET" });
      if (!mounted) return;

      if (res.error || !res.data) {
        setError(res.error?.message || "Unable to load hub metrics");
        setMetrics({ active_riders: 0, open_incidents: 0, risk_quotient: 0, hub_name: "Hub Zone" });
      } else {
        setMetrics(res.data);
      }
      setIsLoading(false);
    }

    load();
    return () => {
      mounted = false;
    };
  }, []);

  const triggerOracle = () => {
    setOracleMessage("Risk oracle trigger is queued for internal rollout.");
    setTimeout(() => setOracleMessage(null), 2200);
  };

  return (
    <HubPageCrossfade>
      <div className="max-w-7xl mx-auto space-y-8">
        {isLoading && (
          <div className="fixed inset-0 z-[999] bg-[var(--color-hub-bg)] flex items-center justify-center">
            <span className="material-symbols-outlined animate-spin text-[var(--color-hub-secondary)] text-4xl">autorenew</span>
          </div>
        )}

        {error && (
          <div className="bg-[var(--color-hub-error)]/10 border border-[var(--color-hub-error)]/20 text-[var(--color-hub-error)] text-xs font-['DM_Sans'] rounded-lg px-4 py-3">
            {error}
          </div>
        )}

        {oracleMessage && (
          <div className="bg-[var(--color-hub-secondary)]/10 border border-[var(--color-hub-secondary)]/20 text-[var(--color-hub-secondary)] text-xs font-['DM_Sans'] rounded-lg px-4 py-3">
            {oracleMessage}
          </div>
        )}
        
        {/* Header Array */}
        <header className="flex justify-between items-end mb-12">
          <div>
            <h1 className="text-4xl font-['Syne'] font-black text-white tracking-tighter mb-2">Live Terminal</h1>
            <p className="text-[var(--color-hub-text)]/50 text-sm font-['DM_Sans']">System metrics and live fleet telemetry. {metrics?.hub_name || "Hub Zone"}</p>
          </div>
          <div className="flex gap-3">
            <button onClick={triggerOracle} className="bg-[var(--color-hub-secondary)] text-[#00210c] px-6 py-2.5 rounded-lg text-sm font-bold shadow-[0_0_20px_rgba(74,222,128,0.2)] active:scale-95 transition-transform">
              Action Risk Oracle
            </button>
          </div>
        </header>

        {/* Core KPIs - No-Line style */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-[var(--color-hub-surface-low)] rounded-2xl p-6">
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-hub-text)]/50 uppercase tracking-widest">Active Riders</span>
              <span className="material-symbols-outlined text-[var(--color-hub-secondary)] text-lg">two_wheeler</span>
            </div>
            <div className="flex items-end gap-3">
              <span className="text-4xl font-['Syne'] font-bold text-white">{Number(metrics?.active_riders || 0).toLocaleString("en-IN")}</span>
              <span className="text-sm font-medium text-[var(--color-hub-secondary)] mb-1 bg-[var(--color-hub-secondary)]/10 px-2 py-0.5 rounded">+12%</span>
            </div>
          </div>
          
          <div className="bg-[var(--color-hub-surface-low)] rounded-2xl p-6">
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-hub-text)]/50 uppercase tracking-widest">Open Incidents</span>
              <span className="material-symbols-outlined text-[var(--color-hub-error)] text-lg border border-[var(--color-hub-error)]/20 p-1 rounded">emergency</span>
            </div>
            <div className="flex items-end gap-3">
              <span className="text-4xl font-['Syne'] font-bold text-white">{Number(metrics?.open_incidents || 0).toLocaleString("en-IN")}</span>
              <span className="text-sm font-medium text-[var(--color-hub-error)] mb-1 bg-[var(--color-hub-error)]/10 px-2 py-0.5 rounded">3 Critical</span>
            </div>
          </div>

          <div className="bg-[var(--color-hub-surface-low)] rounded-2xl p-6">
            <div className="flex items-center justify-between mb-4">
              <span className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-hub-text)]/50 uppercase tracking-widest">Risk Quotient</span>
              <span className="material-symbols-outlined text-yellow-400 text-lg">public</span>
            </div>
            <div className="flex items-end gap-3">
              <span className="text-4xl font-['Syne'] font-bold text-white">{Number(metrics?.risk_quotient || 0).toFixed(2)}</span>
              <span className="text-sm font-medium text-yellow-400 mb-1">Band Moderate</span>
            </div>
          </div>
        </div>

        {/* Mapping Space Approximation */}
        <div className="w-full h-96 bg-[var(--color-hub-surface-high)] rounded-3xl border-2 border-[var(--color-hub-surface-low)] relative overflow-hidden flex items-center justify-center group">
          <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCI+PGNpcmNsZSBjeD0iMiIgY3k9IjIiIHI9IjEiIGZpbGw9IiMzMjM0M2UiLz48L3N2Zz4=')] opacity-50" />
          <div className="z-10 bg-[var(--color-hub-surface-low)] px-6 py-3 rounded-full flex items-center gap-3">
            <span className="material-symbols-outlined text-[var(--color-hub-secondary)] animate-pulse">radar</span>
            <span className="font-['DM_Sans'] text-sm text-[var(--color-hub-text)]">Live Fleet Telemetry Embedded Map Matrix</span>
          </div>
        </div>

      </div>
    </HubPageCrossfade>
  );
}
