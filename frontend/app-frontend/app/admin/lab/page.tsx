"use client";

import { AdminInstantLoad } from "@/lib/motion/safeWrappers";
import { useEffect, useState, useCallback } from "react";
import { fetchApi, adminPath } from "@/lib/api/client";

// ── Param definitions with bounds ────────────────────────────────────────────
const PARAM_DEFS: Record<string, { label: string; min: number; max: number; step: number; unit: string; description: string }> = {
  auto_clear_fs_threshold: { label: "Auto-Clear Fraud Score Threshold", min: 0.20, max: 0.50, step: 0.01, unit: "", description: "Claims with fraud score below this are auto-cleared. Lower = stricter." },
  hard_flag_fs_threshold:  { label: "Hard-Flag Threshold", min: 0.60, max: 0.95, step: 0.01, unit: "", description: "Claims above this are sent to manual review." },
  oracle_threshold:        { label: "Oracle Consensus Threshold", min: 0.50, max: 0.90, step: 0.05, unit: "", description: "Minimum consensus score to fire a trigger event." },
  vov_reward_individual:   { label: "VOV Individual Reward", min: 5, max: 50, step: 5, unit: "₹", description: "Reward paid per confirmed VOV video submission." },
  rain_threshold_mm:       { label: "Rain Trigger Threshold", min: 10, max: 60, step: 5, unit: "mm/hr", description: "Rainfall rate required to trigger rain payout." },
  single_event_cap_pct:    { label: "Single Event Cap %", min: 0.30, max: 0.70, step: 0.05, unit: "", description: "Max payout per trigger event as % of weekly cap." },
  lambda_floor:            { label: "Lambda Floor (Surge)", min: 1.0, max: 2.5, step: 0.1, unit: "×", description: "Minimum surge multiplier for premium calculation." },
  p_base_margin_pct:       { label: "Base Margin %", min: 0.70, max: 0.95, step: 0.01, unit: "", description: "Target gross margin used in premium base calculation." },
};

const GROUP_OPTS = ["control", "group_1", "group_2", "all"];

interface Experiment {
  id: string;
  name: string;
  parameter_name: string;
  parameter_value: string;
  group_id: string;
  active: boolean;
  activated_at: string;
}

export default function AdminLabPage() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [seedLoading, setSeedLoading] = useState(false);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  // New experiment form
  const [form, setForm] = useState({
    name: "threshold_test",
    parameter_name: "auto_clear_fs_threshold",
    parameter_value: "0.40",
    group_id: "group_1",
  });

  const loadExperiments = useCallback(async () => {
    setIsLoading(true);
    // FIX #1: was adminPath("/admin/experiments") = /internal/admin/experiments (404)
    // Correct path: /internal/experiments (ab_experiments_router mounted at /internal with prefix /experiments)
    const res = await fetchApi<{ experiments: Experiment[] }>(adminPath("/experiments"), { method: "GET" });
    if (!res.error && res.data?.experiments) {
      setExperiments(res.data.experiments);
    }
    setIsLoading(false);
  }, []);

  useEffect(() => { loadExperiments(); }, [loadExperiments]);

  const createExperiment = async () => {
    setCreating(true);
    setMessage(null);
    const res = await fetchApi<any>(adminPath("/experiments"), {
      method: "POST",
      body: JSON.stringify(form),
    });
    if (res.error) {
      setMessage({ type: "err", text: res.error.message || "Create failed" });
    } else {
      setMessage({ type: "ok", text: `Experiment "${form.name}" created for group ${form.group_id}` });
      await loadExperiments();
    }
    setCreating(false);
  };

  const deactivateExperiment = async (id: string) => {
    await fetchApi(adminPath(`/experiments/${id}`), { method: "DELETE" });
    await loadExperiments();
  };

  const seedDefaults = async () => {
    setSeedLoading(true);
    await fetchApi(adminPath("/experiments/defaults"), { method: "GET" });
    setMessage({ type: "ok", text: "Default experiments seeded" });
    await loadExperiments();
    setSeedLoading(false);
  };

  // Quick-apply: a helper that fills the form and creates immediately
  const quickApply = async (param: string, value: string, group: string) => {
    const res = await fetchApi<any>(adminPath("/admin/experiments/set"), {
      method: "POST",
      body: JSON.stringify({
        confirm: "CONFIRM",
        parameter_name: param,
        parameter_value: parseFloat(value),
        group_id: group,
      }),
    });
    if (!res.error) {
      setMessage({ type: "ok", text: `${param} set to ${value} for ${group}` });
      await loadExperiments();
    }
  };

  const paramDef = PARAM_DEFS[form.parameter_name];
  const activeExps = experiments.filter(e => e.active);
  const inactiveExps = experiments.filter(e => !e.active);

  return (
    <AdminInstantLoad>
      <div className="space-y-6 pb-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-['Inter'] font-black text-white tracking-tight">Experiment Lab</h1>
            <p className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 mt-0.5">A/B parameter control · live threshold tuning · group assignment</p>
          </div>
          <button onClick={seedDefaults} disabled={seedLoading}
            className="text-[10px] font-['JetBrains_Mono'] uppercase px-3 py-2 border border-[var(--color-admin-outline)]/30 text-[var(--color-admin-text)]/50 hover:text-white hover:border-[var(--color-admin-outline)]/60 transition-colors disabled:opacity-50">
            {seedLoading ? "SEEDING..." : "SEED DEFAULTS"}
          </button>
        </div>

        {message && (
          <div className={`text-[10px] font-['JetBrains_Mono'] px-4 py-2 border ${message.type === "ok" ? "border-[var(--color-admin-primary)]/30 bg-[var(--color-admin-primary)]/5 text-[var(--color-admin-primary)]" : "border-[var(--color-admin-error)]/30 bg-[var(--color-admin-error)]/5 text-[var(--color-admin-error)]"}`}>
            {message.type === "ok" ? "✓" : "✗"} {message.text}
          </div>
        )}

        {/* Quick-tune panel */}
        <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-4">
          <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70 border-b border-[var(--color-admin-outline)]/20 pb-3">Quick-Tune: Critical Thresholds</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {Object.entries(PARAM_DEFS).slice(0, 4).map(([key, def]) => {
              const activeForControl = experiments.find(e => e.parameter_name === key && e.group_id === "control" && e.active);
              const currentVal = activeForControl ? activeForControl.parameter_value : "—";
              return (
                <div key={key} className="space-y-2 p-3 border border-[var(--color-admin-outline)]/10 bg-[var(--color-admin-bg)]/40">
                  <div className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/50 uppercase">{def.label}</div>
                  <div className="text-lg font-['Inter'] font-bold text-white">{currentVal}{def.unit && currentVal !== "—" ? ` ${def.unit}` : ""}</div>
                  <div className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 leading-relaxed">{def.description}</div>
                  <div className="flex gap-1.5 flex-wrap">
                    {[
                      String(def.min),
                      String(Math.round((def.min + def.max) / 2 * 100) / 100),
                      String(def.max)
                    ].map(v => (
                      <button key={v} onClick={() => quickApply(key, v, "control")}
                        className={`text-[9px] font-['JetBrains_Mono'] px-2 py-0.5 border transition-colors ${currentVal === v ? "border-[var(--color-admin-primary)]/50 bg-[var(--color-admin-primary)]/10 text-[var(--color-admin-primary)]" : "border-[var(--color-admin-outline)]/20 text-[var(--color-admin-text)]/40 hover:text-white hover:border-[var(--color-admin-outline)]/50"}`}>
                        {v}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {/* Create Experiment Form */}
          <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-4">
            <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70 border-b border-[var(--color-admin-outline)]/20 pb-3">Create A/B Experiment</h3>

            <div className="space-y-3">
              <div>
                <label className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 uppercase block mb-1">Experiment Name</label>
                <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                  className="w-full bg-[var(--color-admin-bg)] border border-[var(--color-admin-outline)]/30 px-3 py-2 text-xs font-['JetBrains_Mono'] text-white focus:outline-none focus:border-[var(--color-admin-primary)]/50 placeholder:text-white/20"
                  placeholder="e.g. threshold_test_q2" />
              </div>

              <div>
                <label className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 uppercase block mb-1">Parameter</label>
                <select value={form.parameter_name} onChange={e => setForm(f => ({ ...f, parameter_name: e.target.value }))}
                  className="w-full bg-[var(--color-admin-bg)] border border-[var(--color-admin-outline)]/30 px-3 py-2 text-xs font-['JetBrains_Mono'] text-white focus:outline-none focus:border-[var(--color-admin-primary)]/50">
                  {Object.entries(PARAM_DEFS).map(([k, d]) => (
                    <option key={k} value={k}>{d.label}</option>
                  ))}
                </select>
                {paramDef && (
                  <p className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 mt-1">{paramDef.description}</p>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 uppercase block mb-1">
                    Value {paramDef ? `(${paramDef.min}–${paramDef.max} ${paramDef.unit})` : ""}
                  </label>
                  <input value={form.parameter_value} onChange={e => setForm(f => ({ ...f, parameter_value: e.target.value }))}
                    type="number" step={paramDef?.step || 0.01}
                    className="w-full bg-[var(--color-admin-bg)] border border-[var(--color-admin-outline)]/30 px-3 py-2 text-xs font-['JetBrains_Mono'] text-white focus:outline-none focus:border-[var(--color-admin-primary)]/50" />
                </div>
                <div>
                  <label className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 uppercase block mb-1">Rider Group</label>
                  <select value={form.group_id} onChange={e => setForm(f => ({ ...f, group_id: e.target.value }))}
                    className="w-full bg-[var(--color-admin-bg)] border border-[var(--color-admin-outline)]/30 px-3 py-2 text-xs font-['JetBrains_Mono'] text-white focus:outline-none focus:border-[var(--color-admin-primary)]/50">
                    {GROUP_OPTS.map(g => <option key={g} value={g}>{g}</option>)}
                  </select>
                </div>
              </div>

              <button onClick={createExperiment} disabled={creating}
                className="w-full py-2.5 bg-[var(--color-admin-primary)]/10 border border-[var(--color-admin-primary)]/40 text-[var(--color-admin-primary)] text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest hover:bg-[var(--color-admin-primary)]/20 disabled:opacity-50 transition-colors">
                {creating ? "CREATING..." : "CREATE EXPERIMENT"}
              </button>
            </div>
          </div>

          {/* Active Experiments */}
          <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-3">
            <div className="flex items-center justify-between border-b border-[var(--color-admin-outline)]/20 pb-3">
              <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70">
                Active Experiments ({activeExps.length})
              </h3>
              <button onClick={loadExperiments} className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 hover:text-white uppercase">REFRESH</button>
            </div>

            {isLoading ? (
              <div className="space-y-2">
                {[...Array(4)].map((_, i) => <div key={i} className="h-12 bg-[var(--color-admin-outline)]/10 animate-pulse" />)}
              </div>
            ) : activeExps.length === 0 ? (
              <div className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 py-6 text-center">
                No active experiments. Create one or seed defaults.
              </div>
            ) : (
              <div className="space-y-2 overflow-y-auto max-h-72 custom-scrollbar">
                {activeExps.map(exp => (
                  <div key={exp.id} className="flex items-center justify-between p-3 border border-[var(--color-admin-primary)]/10 bg-[var(--color-admin-primary)]/5 group">
                    <div>
                      <div className="text-[10px] font-['JetBrains_Mono'] font-bold text-white">{exp.name}</div>
                      <div className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/50 mt-0.5">
                        {exp.parameter_name} = <span className="text-[var(--color-admin-primary)]">{exp.parameter_value}</span> · {exp.group_id}
                      </div>
                    </div>
                    <button onClick={() => deactivateExperiment(exp.id)}
                      className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 hover:text-[var(--color-admin-error)] border border-transparent hover:border-[var(--color-admin-error)]/30 px-2 py-1 transition-colors opacity-0 group-hover:opacity-100">
                      KILL
                    </button>
                  </div>
                ))}
              </div>
            )}

            {inactiveExps.length > 0 && (
              <details className="mt-3">
                <summary className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 uppercase cursor-pointer hover:text-white">
                  {inactiveExps.length} archived experiments
                </summary>
                <div className="space-y-1 mt-2 max-h-40 overflow-y-auto">
                  {inactiveExps.slice(0, 10).map(exp => (
                    <div key={exp.id} className="flex items-center justify-between px-3 py-2 border border-[var(--color-admin-outline)]/10 opacity-50">
                      <div className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/50">{exp.name} · {exp.parameter_name}={exp.parameter_value}</div>
                      <span className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30">INACTIVE</span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        </div>

        {/* Impact note */}
        <div className="border border-[var(--color-admin-outline)]/10 bg-[var(--color-admin-surface)] p-4">
          <div className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 leading-relaxed">
            <span className="text-[var(--color-admin-primary)] font-bold">HOW A/B WORKS:</span> Riders are deterministically assigned to groups based on SHA-256(rider_id + experiment_name). Same rider always gets same group.
            Group "control" = default behavior. "group_1"/"group_2" = test variants. "all" = applies to every rider immediately.
            Changes take effect within 15 minutes as oracle cycles pick up new parameters.
          </div>
        </div>
      </div>
    </AdminInstantLoad>
  );
}