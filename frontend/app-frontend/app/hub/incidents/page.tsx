"use client";

import { HubPageCrossfade } from "@/lib/motion/safeWrappers";
import { useEffect, useMemo, useState } from "react";
import { fetchApi, hubPath } from "@/lib/api/client";
import { HubIncident } from "@/lib/api/types";

function normalizeIncidentsPayload(payload: unknown): HubIncident[] {
  if (Array.isArray(payload)) return payload as HubIncident[];
  if (!payload || typeof payload !== "object") return [];

  const maybeWrapped = payload as {
    items?: unknown;
    incidents?: unknown;
    rows?: unknown;
    data?: unknown;
  };

  if (Array.isArray(maybeWrapped.items)) return maybeWrapped.items as HubIncident[];
  if (Array.isArray(maybeWrapped.incidents)) return maybeWrapped.incidents as HubIncident[];
  if (Array.isArray(maybeWrapped.rows)) return maybeWrapped.rows as HubIncident[];
  if (Array.isArray(maybeWrapped.data)) return maybeWrapped.data as HubIncident[];

  return [];
}

export default function IncidentsMatrix() {
  const [incidents, setIncidents] = useState<HubIncident[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const loadIncidents = async () => {
    const res = await fetchApi<unknown>(hubPath("/hub/incidents"), { method: "GET" });
    if (res.error || !res.data) {
      setError(res.error?.message || "Unable to load incidents");
      setIncidents([]);
      return;
    }
    setError(null);
    setIncidents(normalizeIncidentsPayload(res.data));
  };

  useEffect(() => {
    let mounted = true;
    async function load() {
      setIsLoading(true);
      await loadIncidents();
      if (mounted) setIsLoading(false);
    }
    load();
    return () => {
      mounted = false;
    };
  }, []);

  const visualIncidents = useMemo(() => {
    const list = Array.isArray(incidents) ? incidents : [];
    return list.slice(0, 8);
  }, [incidents]);

  const runIncidentAction = async (id: string, action: "triage" | "resolve") => {
    setActionLoading(id + action);

    const actionCandidates =
      action === "triage"
        ? ["acknowledge", "triage"]
        : ["resolve", "flag"];

    let lastError: string | null = null;
    let updated = false;

    for (const candidate of actionCandidates) {
      const res = await fetchApi<{ status: string }>(hubPath(`/hub/incidents/${id}`), {
        method: "PATCH",
        body: JSON.stringify({ action: candidate }),
      });

      if (!res.error) {
        updated = true;
        break;
      }

      lastError = res.error.message || "Unable to update incident action";
    }

    if (!updated) {
      setError(lastError || "Unable to update incident action");
      setActionLoading(null);
      return;
    }

    await loadIncidents();
    setActionLoading(null);
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
        
        <header className="mb-8 border-l-4 border-[var(--color-hub-error)] pl-6 py-2">
          <h1 className="text-3xl font-['Syne'] font-bold text-white mb-2">Incident Matrix</h1>
          <p className="text-[var(--color-hub-text)]/50 text-sm font-['DM_Sans']">Tracking structural claims, environmental hazards, and active emergencies.</p>
        </header>

        {/* Heavy Data Cards (Actionable) */}
        <div className="space-y-4">
          {visualIncidents.length === 0 ? (
            <div className="bg-[var(--color-hub-surface-low)] rounded-2xl p-6 text-[var(--color-hub-text)]/60 text-sm font-['DM_Sans']">No incidents found</div>
          ) : (
            visualIncidents.map((incident, idx) => {
              const critical = incident.status === "active" || incident.status === "detected";
              const icon = critical ? "emergency" : "warning";
              const heading = `${incident.trigger_type.toUpperCase()} Event`;
              const ts = new Date(incident.triggered_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });

              return (
                <div key={incident.id} className={`bg-[var(--color-hub-surface-low)] hover:bg-[var(--color-hub-surface-high)] rounded-2xl p-6 transition-colors ${idx === 0 ? 'border border-[var(--color-hub-error)]/20 relative overflow-hidden shadow-lg shadow-[var(--color-hub-error)]/5' : ''} flex justify-between items-center cursor-pointer group`}>
                  {idx === 0 && <div className="absolute left-0 top-0 bottom-0 w-1 bg-[var(--color-hub-error)]" />}
                  <div className="flex items-center gap-6">
                    <div className={`w-14 h-14 rounded-xl ${critical ? 'bg-[var(--color-hub-error)]/10 text-[var(--color-hub-error)]' : 'bg-yellow-500/10 text-yellow-500'} flex flex-col items-center justify-center`}>
                      <span className="material-symbols-outlined font-bold text-2xl">{icon}</span>
                    </div>
                    <div>
                      <div className="flex gap-3 items-center mb-1">
                        <h3 className="text-white font-['Syne'] font-bold text-xl">{heading}</h3>
                        <span className={`${critical ? 'bg-[var(--color-hub-error)]' : 'bg-yellow-500'} text-[#000] text-[10px] font-bold px-2 py-0.5 rounded`}>{incident.status.toUpperCase()}</span>
                      </div>
                      <p className="text-[var(--color-hub-text)]/60 text-sm">Affected Riders: {incident.affected_rider_count} • Oracle: {Number(incident.oracle_score || 0).toFixed(2)}</p>
                    </div>
                  </div>
                  <div className="text-right flex items-center gap-6">
                     <div className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-hub-text)]/40 text-right">
                       {ts} <br/> Triggered
                     </div>
                     <div className="flex items-center gap-2">
                       <button
                         onClick={(e) => { e.stopPropagation(); runIncidentAction(incident.id, "triage"); }}
                         className="text-[10px] font-bold px-2 py-1 rounded bg-white/10 text-white"
                         disabled={actionLoading !== null}
                       >
                         {actionLoading === incident.id + "triage" ? "..." : "Triage"}
                       </button>
                       <button
                         onClick={(e) => { e.stopPropagation(); runIncidentAction(incident.id, "resolve"); }}
                         className="text-[10px] font-bold px-2 py-1 rounded bg-[var(--color-hub-secondary)]/20 text-[var(--color-hub-secondary)]"
                         disabled={actionLoading !== null}
                       >
                         {actionLoading === incident.id + "resolve" ? "..." : "Resolve"}
                       </button>
                       <span className="material-symbols-outlined text-[var(--color-hub-text)] group-hover:text-white transition-colors group-hover:translate-x-1 duration-300">chevron_right</span>
                     </div>
                  </div>
                </div>
              );
            })
          )}

        </div>

      </div>
    </HubPageCrossfade>
  );
}
