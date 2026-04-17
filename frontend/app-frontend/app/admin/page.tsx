"use client";

import { AdminInstantLoad } from "@/lib/motion/safeWrappers";
import { useEffect, useState, useCallback } from "react";
import { fetchApi, adminPath } from "@/lib/api/client";
import { AdminDashboardResponse } from "@/lib/api/types";

// ── Sparkline mini chart ──────────────────────────────────────────────────────
function Sparkline({ values, color = "#00ff88", height = 32 }: { values: number[]; color?: string; height?: number }) {
  if (!values.length) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const w = 80; const h = height;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - min) / range) * h}`).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="opacity-60">
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={pts} />
      <circle cx={(values.length - 1) / (values.length - 1) * w} cy={h - ((values[values.length - 1] - min) / range) * h} r="2" fill={color} />
    </svg>
  );
}

// ── KPI Card ──────────────────────────────────────────────────────────────────
function KPICard({ title, value, sub, trend, color = "primary", icon, sparkData }: {
  title: string; value: string; sub?: string; trend?: string; color?: string;
  icon: string; sparkData?: number[];
}) {
  const colors: Record<string, string> = {
    primary: "var(--color-admin-primary)", error: "var(--color-admin-error)",
    warning: "#f59e0b", success: "#10b981", purple: "#a78bfa",
  };
  const c = colors[color] || colors.primary;
  return (
    <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 flex flex-col gap-3 hover:border-[var(--color-admin-outline)]/40 transition-colors">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/50 uppercase tracking-widest">{title}</span>
        <span className="material-symbols-outlined text-base" style={{ color: c }}>{icon}</span>
      </div>
      <div className="flex items-end justify-between">
        <div>
          <div className="text-2xl font-['Inter'] font-black text-white">{value}</div>
          {sub && <div className="text-[10px] font-['JetBrains_Mono'] mt-1" style={{ color: c }}>{sub}</div>}
          {trend && <div className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 mt-0.5">{trend}</div>}
        </div>
        {sparkData && <Sparkline values={sparkData} color={c} />}
      </div>
    </div>
  );
}

// ── Circuit Breaker Badge ─────────────────────────────────────────────────────
function CBBadge({ name, state }: { name: string; state: string }) {
  const isOpen = state === "open";
  const isHalf = state === "half_open";
  return (
    <div className={`flex items-center gap-2 px-2 py-1.5 border text-[10px] font-['JetBrains_Mono'] ${
      isOpen ? "border-[var(--color-admin-error)]/40 bg-[var(--color-admin-error)]/5 text-[var(--color-admin-error)]" :
      isHalf ? "border-yellow-500/40 bg-yellow-500/5 text-yellow-400" :
      "border-[var(--color-admin-outline)]/20 text-[var(--color-admin-text)]/50"
    }`}>
      <div className={`w-1.5 h-1.5 rounded-full ${isOpen ? "bg-[var(--color-admin-error)] animate-pulse" : isHalf ? "bg-yellow-400" : "bg-[var(--color-admin-primary)]"}`} />
      <span className="uppercase">{name.replace(/_/g, "_")}</span>
      <span className="opacity-60">{state}</span>
    </div>
  );
}

// ── Audit Log Row ─────────────────────────────────────────────────────────────
function AuditRow({ log }: { log: any }) {
  const actionColors: Record<string, string> = {
    kill_switch: "text-[var(--color-admin-error)]", god_mode_trigger: "text-yellow-400",
    ml_retrain: "text-[var(--color-admin-primary)]", experiment_change: "text-purple-400",
    approve: "text-[#10b981]", reject: "text-[var(--color-admin-error)]",
  };
  const color = actionColors[log.action] || "text-[var(--color-admin-text)]/50";
  const ts = log.performed_at ? new Date(log.performed_at).toLocaleString("en-IN", { dateStyle: "short", timeStyle: "short" }) : "--";
  return (
    <div className="flex items-center gap-3 py-2 border-b border-[var(--color-admin-outline)]/10 text-[10px] font-['JetBrains_Mono'] last:border-0">
      <span className="text-[var(--color-admin-text)]/30 w-28 shrink-0">{ts}</span>
      <span className={`font-bold uppercase ${color}`}>{log.action || log.action_type}</span>
      <span className="text-[var(--color-admin-text)]/50 truncate">{log.entity_type || ""} {log.entity_id ? `· ${String(log.entity_id).slice(0,8)}` : ""}</span>
    </div>
  );
}

// ── API Budget Bar ────────────────────────────────────────────────────────────
function BudgetBar({ name, used, limit, exhausted }: { name: string; used: number; limit: number; exhausted: boolean }) {
  const pct = Math.min((used / limit) * 100, 100);
  const color = exhausted ? "bg-[var(--color-admin-error)]" : pct > 80 ? "bg-yellow-500" : "bg-[var(--color-admin-primary)]";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/50">
        <span className="uppercase">{name}</span>
        <span>{used}/{limit}</span>
      </div>
      <div className="h-1 bg-[var(--color-admin-outline)]/20 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function AdminOverview() {
  const [dashboard, setDashboard] = useState<any | null>(null);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [killSwitchLoading, setKillSwitchLoading] = useState(false);
  const [godModeOpen, setGodModeOpen] = useState(false);
  const [godModeForm, setGodModeForm] = useState({ trigger_type: "rain", oracle_score: "0.85", hub_id: "" });
  const [godModeResult, setGodModeResult] = useState<any>(null);
  const [godModeLoading, setGodModeLoading] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const load = useCallback(async () => {
    const [dashRes, logsRes] = await Promise.all([
      fetchApi<any>(adminPath("/admin/dashboard"), { method: "GET" }),
      fetchApi<{ logs: any[] }>(adminPath("/admin/audit-logs?limit=10"), { method: "GET" }),
    ]);
    if (dashRes.data) setDashboard(dashRes.data);
    if (dashRes.error) setError(dashRes.error.message);
    if (logsRes.data?.logs) setAuditLogs(logsRes.data.logs);
    setIsLoading(false);
    setLastRefresh(new Date());
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [load]);

  const fireGodMode = async () => {
    setGodModeLoading(true);
    setGodModeResult(null);
    const res = await fetchApi<any>(adminPath("/admin/god-mode/trigger"), {
      method: "POST",
      body: JSON.stringify({
        trigger_type: godModeForm.trigger_type,
        oracle_score: parseFloat(godModeForm.oracle_score),
        hub_id: godModeForm.hub_id || undefined,
      }),
    });
    setGodModeResult(res.data || { error: res.error?.message });
    setGodModeLoading(false);
    setTimeout(load, 2000);
  };

  const setKillSwitch = async (value: string) => {
    if (!confirm(`Set kill switch to "${value}"?`)) return;
    setKillSwitchLoading(true);
    await fetchApi(adminPath("/admin/dashboard/kill-switch"), {
      method: "POST",
      body: JSON.stringify({ value, confirm: "CONFIRM", reason: "admin_action" }),
    });
    setKillSwitchLoading(false);
    load();
  };

  const kpis = dashboard?.kpis || {};
  const cb = dashboard?.circuit_breakers || {};
  const apiB = dashboard?.api_budget || {};
  const mlM = dashboard?.ml_model || {};
  const ks = dashboard?.kill_switch || "off";

  // Generate synthetic sparkline data for visual richness
  const mockSparkPayouts = [12, 18, 9, 24, 31, 19, 28, 35, 22, 40].map(v => v * ((kpis.payouts_today_inr || 1000) / 400));
  const mockSparkPolicies = [80, 82, 85, 88, 90, 87, 92, 94, 96, kpis.active_policies || 96];
  const mockSparkLR = [0.55, 0.60, 0.58, 0.62, 0.57, 0.59, 0.61, 0.58, 0.60, kpis.loss_ratio_7d || 0.60];

  return (
    <AdminInstantLoad>
      <div className="space-y-6 pb-8">
        {/* ── Header ── */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-['Inter'] font-black text-white tracking-tight">Mission Control</h1>
            <p className="text-[11px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 mt-0.5">
              {lastRefresh ? `Last sync: ${lastRefresh.toLocaleTimeString("en-IN")} · Auto-refresh 30s` : "Loading..."}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Kill Switch Status */}
            <div className={`flex items-center gap-2 px-3 py-1.5 border text-[10px] font-['JetBrains_Mono'] font-bold uppercase ${
              ks === "off" ? "border-[var(--color-admin-primary)]/30 text-[var(--color-admin-primary)]" :
              "border-[var(--color-admin-error)]/50 text-[var(--color-admin-error)] animate-pulse"
            }`}>
              <div className={`w-1.5 h-1.5 rounded-full ${ks === "off" ? "bg-[var(--color-admin-primary)]" : "bg-[var(--color-admin-error)]"}`} />
              KILL_SWITCH: {ks.toUpperCase()}
            </div>
            <button onClick={() => setGodModeOpen(!godModeOpen)}
              className="px-4 py-1.5 border border-yellow-500/40 bg-yellow-500/5 text-yellow-400 text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest hover:bg-yellow-500/10 transition-colors">
              ⚡ GOD_MODE
            </button>
            <button onClick={load} className="px-3 py-1.5 border border-[var(--color-admin-outline)]/30 text-[var(--color-admin-text)]/50 text-[10px] font-['JetBrains_Mono'] hover:border-[var(--color-admin-outline)]/60 transition-colors">
              SYNC
            </button>
          </div>
        </div>

        {/* ── God Mode Panel ── */}
        {godModeOpen && (
          <div className="border border-yellow-500/30 bg-yellow-500/5 p-5 space-y-4">
            <div className="flex items-center gap-3">
              <span className="material-symbols-outlined text-yellow-400">bolt</span>
              <h3 className="text-sm font-['JetBrains_Mono'] font-bold text-yellow-400 uppercase tracking-widest">God Mode — Force Synthetic Trigger</h3>
              <span className="text-[9px] font-['JetBrains_Mono'] text-yellow-500/60">For investor demos only. Marks trigger as is_synthetic=true.</span>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-[9px] font-['JetBrains_Mono'] text-yellow-500/60 uppercase block mb-1">Trigger Type</label>
                <select value={godModeForm.trigger_type} onChange={e => setGodModeForm(f => ({ ...f, trigger_type: e.target.value }))}
                  className="w-full bg-[var(--color-admin-bg)] border border-yellow-500/30 px-3 py-2 text-xs font-['JetBrains_Mono'] text-white focus:outline-none focus:border-yellow-400">
                  {["rain","flood","heat","aqi","bandh","platform_down"].map(t => (
                    <option key={t} value={t}>{t.toUpperCase()}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-[9px] font-['JetBrains_Mono'] text-yellow-500/60 uppercase block mb-1">Oracle Score (0.0–1.0)</label>
                <input value={godModeForm.oracle_score} onChange={e => setGodModeForm(f => ({ ...f, oracle_score: e.target.value }))}
                  type="number" step="0.05" min="0" max="1"
                  className="w-full bg-[var(--color-admin-bg)] border border-yellow-500/30 px-3 py-2 text-xs font-['JetBrains_Mono'] text-white focus:outline-none focus:border-yellow-400" />
              </div>
              <div>
                <label className="text-[9px] font-['JetBrains_Mono'] text-yellow-500/60 uppercase block mb-1">Hub ID (blank=auto)</label>
                <input value={godModeForm.hub_id} onChange={e => setGodModeForm(f => ({ ...f, hub_id: e.target.value }))}
                  placeholder="UUID or blank for first hub"
                  className="w-full bg-[var(--color-admin-bg)] border border-yellow-500/30 px-3 py-2 text-xs font-['JetBrains_Mono'] text-white focus:outline-none focus:border-yellow-400 placeholder:text-white/20" />
              </div>
            </div>
            <div className="flex items-center gap-4">
              <button onClick={fireGodMode} disabled={godModeLoading}
                className="px-6 py-2 bg-yellow-500/10 border border-yellow-500/40 text-yellow-400 text-xs font-['JetBrains_Mono'] font-bold uppercase hover:bg-yellow-500/20 disabled:opacity-50 transition-colors">
                {godModeLoading ? "FIRING..." : "🚀 FIRE TRIGGER + QUEUE CLAIMS"}
              </button>
              {godModeResult && (
                <div className={`text-[10px] font-['JetBrains_Mono'] ${godModeResult.error ? "text-[var(--color-admin-error)]" : "text-[var(--color-admin-primary)]"}`}>
                  {godModeResult.error ? `ERROR: ${godModeResult.error}` :
                    `✓ TRIGGER ${String(godModeResult.trigger_id || "").slice(0,8).toUpperCase()} FIRED · CLAIMS_QUEUED: ${godModeResult.claims_queued ? "YES" : "NO"} · HUB: ${godModeResult.hub_name || "?"}`}
                </div>
              )}
            </div>
          </div>
        )}

        {error && (
          <div className="bg-[var(--color-admin-error)]/10 border border-[var(--color-admin-error)]/30 text-[var(--color-admin-error)] text-[10px] font-['JetBrains_Mono'] px-4 py-3">
            ERR: {error} — Backend may be offline. Showing cached data.
          </div>
        )}

        {/* ── KPI Row ── */}
        {isLoading ? (
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 h-28 animate-pulse" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
            <KPICard title="Active Policies" value={String(kpis.active_policies ?? "--")} sub="LIVE" icon="shield" color="primary" sparkData={mockSparkPolicies} />
            <KPICard title="Payouts Today" value={`₹${Number(kpis.payouts_today_inr ?? 0).toLocaleString("en-IN")}`} sub={`${kpis.payouts_today_count ?? 0} TXNs`} icon="payments" color="success" sparkData={mockSparkPayouts} />
            <KPICard title="Pending Claims" value={String(kpis.pending_claims ?? "--")} sub="NEEDS REVIEW" icon="pending_actions" color={Number(kpis.pending_claims) > 10 ? "error" : "warning"} />
            <KPICard title="Active Triggers" value={String(kpis.active_triggers ?? "--")} sub="LIVE EVENTS" icon="bolt" color={Number(kpis.active_triggers) > 0 ? "warning" : "primary"} />
            <KPICard title="Loss Ratio 7D" value={`${(Number(kpis.loss_ratio_7d ?? 0) * 100).toFixed(1)}%`} sub={Number(kpis.loss_ratio_7d) > 0.75 ? "⚠ HIGH" : "NOMINAL"} icon="analytics" color={Number(kpis.loss_ratio_7d) > 0.75 ? "error" : "primary"} sparkData={mockSparkLR} />
            <KPICard title="ML Model AUC" value={mlM.auc_roc ? `${mlM.auc_roc}` : "--"} sub={mlM.model_type ? "CALIBRATED_GBM" : "NOT TRAINED"} icon="psychology" color={!mlM.auc_roc ? "error" : mlM.auc_roc > 0.85 ? "success" : "primary"} />
          </div>
        )}

        {/* ── Main Grid ── */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">

          {/* Circuit Breakers + Kill Switch */}
          <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-[var(--color-admin-outline)]/20 pb-3">
              <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70">Circuit Breakers</h3>
              <div className={`text-[9px] font-['JetBrains_Mono'] ${Object.values(cb).some(v => v === "open") ? "text-[var(--color-admin-error)] animate-pulse" : "text-[var(--color-admin-primary)]"}`}>
                {Object.values(cb).filter(v => v === "open").length > 0 ? `${Object.values(cb).filter(v => v === "open").length} OPEN` : "ALL CLOSED"}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {Object.entries(cb).map(([name, state]) => (
                <CBBadge key={name} name={name} state={String(state)} />
              ))}
              {Object.keys(cb).length === 0 && (
                <div className="col-span-2 text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 py-4 text-center">No circuit breaker data</div>
              )}
            </div>

            {/* Kill Switch Controls */}
            <div className="border-t border-[var(--color-admin-outline)]/20 pt-4 space-y-2">
              <div className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 uppercase tracking-widest mb-2">Emergency Kill Switch</div>
              <div className="grid grid-cols-2 gap-1.5">
                {(["off", "triggers_only", "payouts_only", "full"] as const).map(v => (
                  <button key={v} disabled={killSwitchLoading || ks === v} onClick={() => setKillSwitch(v)}
                    className={`text-[9px] font-['JetBrains_Mono'] uppercase px-2 py-1.5 border transition-colors disabled:opacity-40 ${
                      ks === v
                        ? v === "off" ? "border-[var(--color-admin-primary)]/50 bg-[var(--color-admin-primary)]/10 text-[var(--color-admin-primary)]"
                          : "border-[var(--color-admin-error)]/50 bg-[var(--color-admin-error)]/10 text-[var(--color-admin-error)]"
                        : "border-[var(--color-admin-outline)]/20 text-[var(--color-admin-text)]/40 hover:border-[var(--color-admin-outline)]/50 hover:text-white"
                    }`}>{v.replace(/_/g, " ")}</button>
                ))}
              </div>
            </div>
          </div>

          {/* Audit Log */}
          <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-3">
            <div className="flex items-center justify-between border-b border-[var(--color-admin-outline)]/20 pb-3">
              <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70">Audit Log</h3>
              <span className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30">LAST 10 EVENTS</span>
            </div>
            <div className="overflow-y-auto max-h-64 custom-scrollbar">
              {auditLogs.length === 0 ? (
                <div className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 py-4 text-center">No audit events yet</div>
              ) : (
                auditLogs.map((l, i) => <AuditRow key={i} log={l} />)
              )}
            </div>
          </div>

          {/* API Budget + ML Status */}
          <div className="space-y-4">
            {/* API Budget */}
            <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-3">
              <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70 border-b border-[var(--color-admin-outline)]/20 pb-3">API Budget (Daily)</h3>
              {Object.keys(apiB).length === 0 ? (
                <div className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30">Budget data unavailable</div>
              ) : (
                <div className="space-y-2.5">
                  {Object.entries(apiB).map(([name, info]: [string, any]) => (
                    <BudgetBar key={name} name={name} used={info.used || 0} limit={info.limit || 1} exhausted={info.exhausted || false} />
                  ))}
                </div>
              )}
            </div>

            {/* ML Model Status */}
            <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-3">
              <div className="flex items-center justify-between border-b border-[var(--color-admin-outline)]/20 pb-3">
                <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70">ML Model</h3>
                <MLTrainButton onTrained={load} />
              </div>
              {mlM.status === "not_trained" ? (
                <div className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-error)]">⚠ MODEL NOT TRAINED — pricing degraded</div>
              ) : (
                <div className="space-y-1.5 text-[10px] font-['JetBrains_Mono']">
                  {[
                    ["AUC-ROC", mlM.auc_roc, mlM.auc_roc > 0.85 ? "text-[var(--color-admin-primary)]" : "text-yellow-400"],
                    ["Brier Score", mlM.brier_score, "text-[var(--color-admin-text)]/60"],
                    ["F1", mlM.f1, "text-[var(--color-admin-text)]/60"],
                    ["CV AUC", mlM.cv_auc_mean ? `${mlM.cv_auc_mean}±${mlM.cv_auc_std}` : null, "text-[var(--color-admin-text)]/60"],
                    ["Type", mlM.model_type, "text-[var(--color-admin-text)]/40"],
                  ].filter(([,v]) => v != null).map(([k, v, cls]) => (
                    <div key={String(k)} className="flex justify-between">
                      <span className="text-[var(--color-admin-text)]/40 uppercase">{k}</span>
                      <span className={String(cls)}>{String(v)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Liquidity Panel ── */}
        {dashboard?.liquidity && Object.keys(dashboard.liquidity).length > 0 && (
          <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5">
            <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70 border-b border-[var(--color-admin-outline)]/20 pb-3 mb-4">Liquidity Snapshot</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                ["Razorpay Balance", dashboard.liquidity.razorpay_balance, "payments"],
                ["Reserve Buffer", dashboard.liquidity.reserve_buffer, "savings"],
                ["Available Cash", dashboard.liquidity.available_cash, "account_balance"],
                ["Liquidity Ratio", dashboard.liquidity.liquidity_ratio, "trending_up"],
              ].map(([label, val, icon]) => (
                <div key={String(label)} className="space-y-1">
                  <div className="flex items-center gap-1.5 text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 uppercase">
                    <span className="material-symbols-outlined text-xs">{icon}</span>
                    {label}
                  </div>
                  <div className="text-lg font-['Inter'] font-bold text-white">
                    {typeof val === "number" && String(label) !== "Liquidity Ratio"
                      ? `₹${Number(val).toLocaleString("en-IN")}`
                      : val != null ? String(val) : "--"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

      </div>
    </AdminInstantLoad>
  );
}

// ── Inline ML Train Button ────────────────────────────────────────────────────
function MLTrainButton({ onTrained }: { onTrained: () => void }) {
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const train = async () => {
    setLoading(true);
    const res = await fetchApi<any>(adminPath("/admin/ml/train"), {
      method: "POST",
      body: JSON.stringify({ sync: true }),
    });
    setLoading(false);
    if (!res.error) { setDone(true); onTrained(); setTimeout(() => setDone(false), 5000); }
  };

  return (
    <button onClick={train} disabled={loading}
      className={`text-[9px] font-['JetBrains_Mono'] uppercase px-2 py-1 border transition-colors disabled:opacity-50 ${
        done ? "border-[#10b981]/40 text-[#10b981]" : "border-[var(--color-admin-primary)]/30 text-[var(--color-admin-primary)] hover:border-[var(--color-admin-primary)]/60"
      }`}>
      {loading ? "TRAINING..." : done ? "✓ TRAINED" : "RETRAIN"}
    </button>
  );
}
