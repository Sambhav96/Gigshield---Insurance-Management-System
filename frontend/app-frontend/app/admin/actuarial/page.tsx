"use client";

import { AdminInstantLoad } from "@/lib/motion/safeWrappers";
import { useEffect, useState } from "react";
import { adminService } from "@/lib/api/admin";
import { fetchApi, adminPath } from "@/lib/api/client";

const PARAM_GROUPS = [
  {
    title: "Fraud Thresholds",
    icon: "security",
    params: [
      { key: "auto_clear_fs_threshold", label: "Auto-Clear Threshold", min: 0.20, max: 0.50, step: 0.01, description: "Claims with FS below this are auto-cleared" },
      { key: "hard_flag_fs_threshold",  label: "Hard-Flag Threshold",  min: 0.60, max: 0.95, step: 0.01, description: "Claims above this sent to manual review" },
    ],
  },
  {
    title: "Payout Controls",
    icon: "payments",
    params: [
      { key: "single_event_cap_pct",   label: "Event Cap % of Weekly", min: 0.30, max: 0.70, step: 0.05, description: "Max payout per event as % of weekly cap" },
      { key: "daily_soft_limit_divisor", label: "Daily Soft Limit Divisor", min: 2, max: 7, step: 1, description: "Weekly cap ÷ this = daily continuation limit" },
    ],
  },
  {
    title: "Pricing Parameters",
    icon: "price_change",
    params: [
      { key: "p_base_margin_pct", label: "Base Margin %", min: 0.70, max: 0.95, step: 0.01, description: "Target gross margin for premium calculation" },
      { key: "lambda_floor",      label: "Lambda Floor (Surge)", min: 1.0, max: 2.5, step: 0.1, description: "Min surge multiplier applied to base premium" },
    ],
  },
  {
    title: "Oracle Sensitivity",
    icon: "sensors",
    params: [
      { key: "oracle_threshold", label: "Oracle Consensus Threshold", min: 0.50, max: 0.90, step: 0.05, description: "Min oracle score to fire trigger event" },
    ],
  },
  {
    title: "VOV & Rewards",
    icon: "videocam",
    params: [
      { key: "vov_reward_individual", label: "VOV Individual Reward ₹", min: 5, max: 50, step: 5, description: "₹ reward per confirmed VOV video" },
      { key: "vov_reward_zone_cert",  label: "Zone Cert Bonus ₹",       min: 10, max: 100, step: 10, description: "Additional ₹ for zone certification contribution" },
    ],
  },
  {
    title: "Discount Engine",
    icon: "loyalty",
    params: [
      { key: "max_discount_weeks",     label: "Max Discount Weeks", min: 1, max: 6, step: 1, description: "Max consecutive clean weeks that earn discount" },
      { key: "discount_per_clean_week", label: "Discount Per Clean Week %", min: 1, max: 10, step: 1, description: "Premium discount % per clean (no-payout) week" },
    ],
  },
];

export default function AdminActuarial() {
  const [params, setParams] = useState<Record<string, number>>({});
  const [isLoading, setIsLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [mlVersions, setMlVersions] = useState<any>(null);

  useEffect(() => {
    async function load() {
      setIsLoading(true);
      const [paramsRes, versionsRes] = await Promise.all([
        adminService.getGlobalParameters(),
        fetchApi<any>(adminPath("/admin/ml/versions"), { method: "GET" }),
      ]);
      if (!paramsRes.error && paramsRes.data) setParams(paramsRes.data);
      if (!versionsRes.error && versionsRes.data) setMlVersions(versionsRes.data);
      setIsLoading(false);
    }
    load();
  }, []);

  const saveParam = async (key: string, value: number) => {
    setSaving(key);
    setError(null);
    const res = await adminService.updateGlobalParameters({ [key]: value });
    if (res.error) {
      setError(res.error.message || "Save failed");
    } else {
      setSaved(prev => new Set([...prev, key]));
      setTimeout(() => setSaved(prev => { const n = new Set(prev); n.delete(key); return n; }), 3000);
    }
    setSaving(null);
  };

  const rollback = async (timestamp: string) => {
    if (!confirm(`Rollback ML model to version ${timestamp}?`)) return;
    const res = await fetchApi(adminPath("/admin/ml/rollback"), {
      method: "POST",
      body: JSON.stringify({ timestamp }),
    });
    if (!res.error) {
      alert("Model rolled back successfully");
      window.location.reload();
    }
  };

  return (
    <AdminInstantLoad>
      <div className="space-y-6 pb-8">
        <div>
          <h1 className="text-xl font-['Inter'] font-black text-white tracking-tight">Actuarial Model</h1>
          <p className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 mt-0.5">Live parameter tuning · pricing controls · ML model management</p>
        </div>

        {error && (
          <div className="border border-[var(--color-admin-error)]/30 bg-[var(--color-admin-error)]/5 text-[var(--color-admin-error)] text-[10px] font-['JetBrains_Mono'] px-4 py-3">ERR: {error}</div>
        )}

        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {[...Array(6)].map((_, i) => <div key={i} className="h-40 bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 animate-pulse" />)}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {PARAM_GROUPS.map(group => (
              <div key={group.title} className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-4">
                <div className="flex items-center gap-2 border-b border-[var(--color-admin-outline)]/20 pb-3">
                  <span className="material-symbols-outlined text-[var(--color-admin-primary)] text-base">{group.icon}</span>
                  <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70">{group.title}</h3>
                </div>
                {group.params.map(p => {
                  const val = params[p.key] ?? 0;
                  const isSaving = saving === p.key;
                  const isSaved = saved.has(p.key);
                  return (
                    <div key={p.key} className="space-y-2">
                      <div className="flex items-center justify-between">
                        <label className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/50 uppercase">{p.label}</label>
                        <span className="text-[10px] font-['JetBrains_Mono'] font-bold text-white">{val}</span>
                      </div>
                      <input type="range" min={p.min} max={p.max} step={p.step} value={val}
                        onChange={e => setParams(prev => ({ ...prev, [p.key]: Number(e.target.value) }))}
                        className="w-full accent-[var(--color-admin-primary)] h-1" />
                      <div className="flex items-center justify-between">
                        <span className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30">{p.description}</span>
                        <button onClick={() => saveParam(p.key, val)} disabled={isSaving}
                          className={`text-[9px] font-['JetBrains_Mono'] uppercase px-2 py-0.5 border transition-colors disabled:opacity-50 ${
                            isSaved ? "border-[#10b981]/40 text-[#10b981]" : "border-[var(--color-admin-outline)]/30 text-[var(--color-admin-text)]/40 hover:text-white hover:border-[var(--color-admin-outline)]/60"
                          }`}>
                          {isSaving ? "..." : isSaved ? "✓" : "SAVE"}
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}

        {/* ML Model Version Management */}
        {mlVersions && (
          <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-[var(--color-admin-outline)]/20 pb-3">
              <div className="flex items-center gap-2">
                <span className="material-symbols-outlined text-[var(--color-admin-primary)] text-base">psychology</span>
                <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70">ML Model Versions</h3>
              </div>
              <div className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40">
                {mlVersions.archived_versions?.length || 0} archived · rollback available
              </div>
            </div>

            {/* Current model */}
            {mlVersions.current_model && mlVersions.current_model.auc_roc && (
              <div className="flex items-center gap-4 p-3 border border-[var(--color-admin-primary)]/20 bg-[var(--color-admin-primary)]/5">
                <div className="w-2 h-2 rounded-full bg-[var(--color-admin-primary)] animate-pulse" />
                <div className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/70">
                  LIVE · AUC={mlVersions.current_model.auc_roc} · Brier={mlVersions.current_model.brier_score} · {mlVersions.current_model.model_type}
                </div>
              </div>
            )}

            {/* Archived versions */}
            {mlVersions.archived_versions?.length > 0 && (
              <div className="space-y-1">
                {mlVersions.archived_versions.map((v: any) => (
                  <div key={v.timestamp} className="flex items-center justify-between p-2 border border-[var(--color-admin-outline)]/10 hover:border-[var(--color-admin-outline)]/30 group transition-colors">
                    <div className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/50">
                      v{v.timestamp.replace(/_/g, "-")} · {v.size_kb}kb
                    </div>
                    <button onClick={() => rollback(v.timestamp)}
                      className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 hover:text-yellow-400 border border-transparent hover:border-yellow-400/30 px-2 py-0.5 opacity-0 group-hover:opacity-100 transition-all uppercase">
                      ROLLBACK
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </AdminInstantLoad>
  );
}