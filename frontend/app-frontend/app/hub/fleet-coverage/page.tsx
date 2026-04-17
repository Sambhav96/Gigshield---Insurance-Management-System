"use client";

import { HubPageCrossfade } from "@/lib/motion/safeWrappers";
import { useEffect, useMemo, useState } from "react";
import { fetchApi, hubPath } from "@/lib/api/client";
import { FleetRider } from "@/lib/api/types";

function normalizeFleetPayload(payload: unknown): FleetRider[] {
  if (Array.isArray(payload)) return payload as FleetRider[];
  if (!payload || typeof payload !== "object") return [];

  const maybeWrapped = payload as {
    items?: unknown;
    fleet?: unknown;
    rows?: unknown;
    data?: unknown;
  };

  if (Array.isArray(maybeWrapped.items)) return maybeWrapped.items as FleetRider[];
  if (Array.isArray(maybeWrapped.fleet)) return maybeWrapped.fleet as FleetRider[];
  if (Array.isArray(maybeWrapped.rows)) return maybeWrapped.rows as FleetRider[];
  if (Array.isArray(maybeWrapped.data)) return maybeWrapped.data as FleetRider[];

  return [];
}

export default function FleetCoverage() {
  const [fleet, setFleet] = useState<FleetRider[] | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function load() {
      setIsLoading(true);
      setError(null);

      const res = await fetchApi<unknown>(hubPath("/hub/fleet"), { method: "GET" });
      if (!mounted) return;

      if (res.error || !res.data) {
        setError(res.error?.message || "Unable to load hub fleet");
        setFleet([]);
      } else {
        setFleet(normalizeFleetPayload(res.data));
      }

      setIsLoading(false);
    }

    load();
    return () => {
      mounted = false;
    };
  }, []);

  const filteredFleet = useMemo(() => {
    const list = Array.isArray(fleet) ? fleet : [];
    const q = searchQuery.trim().toLowerCase();
    if (!q) return list;
    return list.filter((r) => {
      const riderId = String(r?.rider_id || "").toLowerCase();
      const riderName = String(r?.name || "").toLowerCase();
      return riderId.includes(q) || riderName.includes(q);
    });
  }, [fleet, searchQuery]);

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
        
        <header className="flex justify-between items-end mb-8">
          <div>
            <h1 className="text-3xl font-['Syne'] font-bold text-white mb-2">Fleet Coverage Matrix</h1>
            <p className="text-[var(--color-hub-text)]/50 text-sm font-['DM_Sans']">Real-time breakdown of insured active logistics personnel.</p>
          </div>
          <div className="flex gap-2">
            <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search ID..." className="bg-[var(--color-hub-surface-high)] rounded-lg px-4 py-2 text-sm text-white border-0 outline-none w-64" />
          </div>
        </header>

        {/* Data List Approximation */}
        <div className="bg-[var(--color-hub-surface-low)] rounded-2xl overflow-hidden">
          <div className="grid grid-cols-5 px-6 py-4 border-b border-[#1f222d] text-[10px] font-['JetBrains_Mono'] text-[var(--color-hub-text)]/40 uppercase tracking-widest">
            <div>Personnel ID</div>
            <div>Status</div>
            <div>Locale Matrix</div>
            <div>Policy Tier</div>
            <div className="text-right">Risk Value</div>
          </div>
          <div className="divide-y divide-[#1f222d]">
            {filteredFleet.length === 0 ? (
              <div className="px-6 py-8 text-sm text-[var(--color-hub-text)]/60 font-['DM_Sans']">No riders found</div>
            ) : (
              filteredFleet.map((r, i) => {
                const riderId = String(r?.rider_id || "unknown");
                const riderStatus = String(r?.status || "unknown");
                const riderLocation = String(r?.last_location || "Hub Zone");
                const riderPlan = String(r?.policy_plan || "None");
                const isActive = riderStatus.includes("Active");
                const isIncident = riderStatus.includes("Incident");

                return (
                <div key={`${riderId}-${i}`} className="grid grid-cols-5 px-6 py-5 items-center hover:bg-[var(--color-hub-surface-high)] transition-colors">
                  <div className="font-['Syne'] font-bold text-white">{riderId.slice(0, 8).toUpperCase()}</div>
                  <div>
                    <span className={`px-2.5 py-1 rounded-full text-xs font-bold ${
                      isActive ? 'bg-[var(--color-hub-secondary)]/10 text-[var(--color-hub-secondary)]' :
                      isIncident ? 'bg-[var(--color-hub-error)]/10 text-[var(--color-hub-error)]' :
                      'bg-[#ffffff10] text-[#a1a1a1]'
                    }`}>
                      {riderStatus}
                    </span>
                  </div>
                  <div className="text-sm text-[var(--color-hub-text)]">{riderLocation}</div>
                  <div className="text-sm font-medium text-white">{riderPlan}</div>
                  <div className="text-right font-['JetBrains_Mono'] text-sm text-[var(--color-hub-text)]/60">₹{Number(r.coverage_cap || 0).toLocaleString("en-IN")} Cover</div>
                </div>
                );
              })
            )}
          </div>
        </div>

      </div>
    </HubPageCrossfade>
  );
}
