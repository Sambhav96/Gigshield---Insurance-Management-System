"use client";

import { AdminInstantLoad } from "@/lib/motion/safeWrappers";
import { useState, useCallback } from "react";
import { fetchApi, adminPath } from "@/lib/api/client";

const CITIES = ["Mumbai", "Bangalore", "Delhi", "Chennai", "Hyderabad", "Pune"];
const TRIGGER_TYPES = ["rain", "flood", "heat", "aqi", "bandh", "platform_down"];
const PLANS = ["basic", "standard", "pro"];

// ── Mini loss ratio bar ───────────────────────────────────────────────────────
function LRBar({ ratio, label }: { ratio: number; label: string }) {
  const pct = Math.min(ratio * 100, 100);
  const color = ratio > 0.85 ? "bg-[var(--color-admin-error)]" : ratio > 0.65 ? "bg-yellow-500" : "bg-[var(--color-admin-primary)]";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[9px] font-['JetBrains_Mono']">
        <span className="text-[var(--color-admin-text)]/50 uppercase">{label}</span>
        <span className={ratio > 0.85 ? "text-[var(--color-admin-error)]" : ratio > 0.65 ? "text-yellow-400" : "text-[var(--color-admin-primary)]"}>
          {(ratio * 100).toFixed(1)}%
        </span>
      </div>
      <div className="h-1.5 bg-[var(--color-admin-outline)]/20 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function AdminSimulationPage() {
  const [backtest, setBacktest] = useState({
    city: "Mumbai", plan: "standard", start_date: "2024-06-01",
    end_date: "2024-09-01", n_synthetic_riders: "100",
  });
  const [stress, setStress] = useState({
    city: "Mumbai", trigger_type: "rain", pct_riders_affected: "0.30",
    avg_duration_hrs: "2.0", avg_income: "700", plan: "standard", tier: "B",
  });
  const [backtestResult, setBacktestResult] = useState<any>(null);
  const [stressResult, setStressResult] = useState<any>(null);
  const [btLoading, setBtLoading] = useState(false);
  const [stLoading, setStLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runBacktest = useCallback(async () => {
    setBtLoading(true);
    setError(null);
    setBacktestResult(null);
    const res = await fetchApi<any>(adminPath("/admin/backtesting/run"), {
      method: "POST",
      body: JSON.stringify({
        city: backtest.city,
        plan: backtest.plan,
        start_date: backtest.start_date,
        end_date: backtest.end_date,
        n_synthetic_riders: Number(backtest.n_synthetic_riders),
      }),
    });
    if (res.error || !res.data) {
      setError(res.error?.message || "Backtest failed");
    } else {
      setBacktestResult(res.data);
    }
    setBtLoading(false);
  }, [backtest]);

  const runStress = useCallback(async () => {
    setStLoading(true);
    setError(null);
    setStressResult(null);
    const res = await fetchApi<any>(adminPath("/admin/stress-test/run"), {
      method: "POST",
      body: JSON.stringify({
        city: stress.city,
        trigger_type: stress.trigger_type,
        pct_riders_affected: Number(stress.pct_riders_affected),
        avg_duration_hrs: Number(stress.avg_duration_hrs),
        avg_income: Number(stress.avg_income),
        plan: stress.plan,
        tier: stress.tier,
      }),
    });
    if (!res.error && res.data) {
      if (res.data.task_id) {
        // Poll for async result
        for (let i = 0; i < 20; i++) {
          await new Promise(r => setTimeout(r, 1500));
          const poll = await fetchApi<any>(adminPath(`/admin/backtesting/status/${res.data.task_id}`));
          if (poll.data?.status === "SUCCESS") { setStressResult(poll.data.result || poll.data); break; }
          if (poll.data?.status === "FAILURE") { setError(poll.data.error || "Stress test failed"); break; }
        }
      } else {
        setStressResult(res.data.results || res.data);
      }
    } else {
      setError(res.error?.message || "Stress test failed");
    }
    setStLoading(false);
  }, [stress]);

  const inputCls = "w-full bg-[var(--color-admin-bg)] border border-[var(--color-admin-outline)]/30 px-3 py-2 text-xs font-['JetBrains_Mono'] text-white focus:outline-none focus:border-[var(--color-admin-primary)]/50";
  const labelCls = "text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 uppercase block mb-1";

  return (
    <AdminInstantLoad>
      <div className="space-y-6 pb-8">
        <div>
          <h1 className="text-xl font-['Inter'] font-black text-white tracking-tight">Simulation Engine</h1>
          <p className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 mt-0.5">Historical backtesting · stress scenarios · loss ratio projection</p>
        </div>

        {error && (
          <div className="border border-[var(--color-admin-error)]/30 bg-[var(--color-admin-error)]/5 text-[var(--color-admin-error)] text-[10px] font-['JetBrains_Mono'] px-4 py-3">
            ERR: {error}
          </div>
        )}

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">

          {/* ── Historical Backtest ── */}
          <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-4">
            <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70 border-b border-[var(--color-admin-outline)]/20 pb-3">
              Historical Backtest
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>City</label>
                <select value={backtest.city} onChange={e => setBacktest(b => ({ ...b, city: e.target.value }))} className={inputCls}>
                  {CITIES.map(c => <option key={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className={labelCls}>Plan</label>
                <select value={backtest.plan} onChange={e => setBacktest(b => ({ ...b, plan: e.target.value }))} className={inputCls}>
                  {PLANS.map(p => <option key={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <label className={labelCls}>Start Date</label>
                <input type="date" value={backtest.start_date} onChange={e => setBacktest(b => ({ ...b, start_date: e.target.value }))} className={inputCls} />
              </div>
              <div>
                <label className={labelCls}>End Date</label>
                <input type="date" value={backtest.end_date} onChange={e => setBacktest(b => ({ ...b, end_date: e.target.value }))} className={inputCls} />
              </div>
              <div>
                <label className={labelCls}>Synthetic Riders</label>
                <input type="number" value={backtest.n_synthetic_riders} onChange={e => setBacktest(b => ({ ...b, n_synthetic_riders: e.target.value }))} className={inputCls} />
              </div>
            </div>
            <button onClick={runBacktest} disabled={btLoading}
              className="w-full py-2.5 bg-[var(--color-admin-primary)]/10 border border-[var(--color-admin-primary)]/40 text-[var(--color-admin-primary)] text-[10px] font-['JetBrains_Mono'] font-bold uppercase hover:bg-[var(--color-admin-primary)]/20 disabled:opacity-50 transition-colors">
              {btLoading ? "RUNNING SIMULATION..." : "RUN HISTORICAL BACKTEST"}
            </button>

            {backtestResult && (
              <div className="space-y-4 border-t border-[var(--color-admin-outline)]/20 pt-4">
                <div className="grid grid-cols-2 gap-3 text-[10px] font-['JetBrains_Mono']">
                  {[
                    ["Total Weeks", backtestResult.summary?.total_weeks],
                    ["Total Triggers", backtestResult.summary?.total_triggers],
                    ["Sim Premiums", `₹${Number(backtestResult.summary?.total_sim_premiums || 0).toLocaleString("en-IN")}`],
                    ["Sim Payouts", `₹${Number(backtestResult.summary?.total_sim_payouts || 0).toLocaleString("en-IN")}`],
                  ].map(([k, v]) => (
                    <div key={String(k)} className="p-2 bg-[var(--color-admin-bg)]/40 border border-[var(--color-admin-outline)]/10">
                      <div className="text-[var(--color-admin-text)]/40 uppercase text-[9px]">{k}</div>
                      <div className="text-white font-bold mt-0.5">{v ?? "--"}</div>
                    </div>
                  ))}
                </div>
                <LRBar ratio={backtestResult.summary?.overall_loss_ratio || 0} label="Overall Loss Ratio" />
                <div className={`text-[10px] font-['JetBrains_Mono'] px-3 py-2 border ${
                  backtestResult.summary?.premium_adequacy === "adequate"
                    ? "border-[var(--color-admin-primary)]/30 bg-[var(--color-admin-primary)]/5 text-[var(--color-admin-primary)]"
                    : backtestResult.summary?.premium_adequacy === "borderline"
                    ? "border-yellow-500/30 bg-yellow-500/5 text-yellow-400"
                    : "border-[var(--color-admin-error)]/30 bg-[var(--color-admin-error)]/5 text-[var(--color-admin-error)]"
                }`}>
                  ADEQUACY: {String(backtestResult.summary?.premium_adequacy || "—").toUpperCase()}
                </div>

                {/* Weekly breakdown mini chart */}
                {backtestResult.weekly_results && (
                  <div>
                    <div className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 uppercase mb-2">Weekly Loss Ratio</div>
                    <div className="flex items-end gap-0.5 h-12">
                      {backtestResult.weekly_results.slice(-12).map((w: any, i: number) => {
                        const lr = w.loss_ratio || 0;
                        const h = Math.max(2, lr * 48);
                        const bg = lr > 0.85 ? "bg-[var(--color-admin-error)]" : lr > 0.65 ? "bg-yellow-500" : "bg-[var(--color-admin-primary)]";
                        return <div key={i} className={`flex-1 ${bg} opacity-70 rounded-sm`} style={{ height: `${h}px` }} title={`W${w.week}: ${(lr*100).toFixed(1)}%`} />;
                      })}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Stress Test ── */}
          <div className="bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-5 space-y-4">
            <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-widest text-[var(--color-admin-text)]/70 border-b border-[var(--color-admin-outline)]/20 pb-3">
              Stress Test Scenario
            </h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>City</label>
                <select value={stress.city} onChange={e => setStress(s => ({ ...s, city: e.target.value }))} className={inputCls}>
                  {CITIES.map(c => <option key={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className={labelCls}>Trigger Type</label>
                <select value={stress.trigger_type} onChange={e => setStress(s => ({ ...s, trigger_type: e.target.value }))} className={inputCls}>
                  {TRIGGER_TYPES.map(t => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className={labelCls}>Riders Affected %</label>
                <input type="number" step="0.05" min="0" max="1" value={stress.pct_riders_affected}
                  onChange={e => setStress(s => ({ ...s, pct_riders_affected: e.target.value }))} className={inputCls} />
              </div>
              <div>
                <label className={labelCls}>Duration (hrs)</label>
                <input type="number" step="0.5" value={stress.avg_duration_hrs}
                  onChange={e => setStress(s => ({ ...s, avg_duration_hrs: e.target.value }))} className={inputCls} />
              </div>
              <div>
                <label className={labelCls}>Avg Income ₹/day</label>
                <input type="number" value={stress.avg_income}
                  onChange={e => setStress(s => ({ ...s, avg_income: e.target.value }))} className={inputCls} />
              </div>
              <div>
                <label className={labelCls}>Plan</label>
                <select value={stress.plan} onChange={e => setStress(s => ({ ...s, plan: e.target.value }))} className={inputCls}>
                  {PLANS.map(p => <option key={p}>{p}</option>)}
                </select>
              </div>
            </div>
            <button onClick={runStress} disabled={stLoading}
              className="w-full py-2.5 bg-yellow-500/5 border border-yellow-500/30 text-yellow-400 text-[10px] font-['JetBrains_Mono'] font-bold uppercase hover:bg-yellow-500/10 disabled:opacity-50 transition-colors">
              {stLoading ? "COMPUTING..." : "RUN STRESS SCENARIO"}
            </button>

            {stressResult && (
              <div className="space-y-3 border-t border-[var(--color-admin-outline)]/20 pt-4">
                <div className="grid grid-cols-2 gap-3 text-[10px] font-['JetBrains_Mono']">
                  {[
                    ["Affected Riders", stressResult.affected_riders],
                    ["Total Payout ₹", stressResult.total_payout_inr ? `₹${Number(stressResult.total_payout_inr).toLocaleString("en-IN")}` : "--"],
                    ["Loss Ratio", stressResult.simulated_loss_ratio != null ? `${(Number(stressResult.simulated_loss_ratio) * 100).toFixed(1)}%` : "--"],
                    ["Action", stressResult.recommended_action],
                  ].map(([k, v]) => (
                    <div key={String(k)} className="p-2 bg-[var(--color-admin-bg)]/40 border border-[var(--color-admin-outline)]/10">
                      <div className="text-[var(--color-admin-text)]/40 uppercase text-[9px]">{k}</div>
                      <div className="text-white font-bold mt-0.5 break-words">{v ?? "--"}</div>
                    </div>
                  ))}
                </div>
                {stressResult.simulated_loss_ratio != null && (
                  <LRBar ratio={Number(stressResult.simulated_loss_ratio)} label="Stress Loss Ratio" />
                )}
              </div>
            )}
          </div>
        </div>

        {/* Info Panel */}
        <div className="border border-[var(--color-admin-outline)]/10 bg-[var(--color-admin-surface)] p-4">
          <div className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/30 leading-relaxed space-y-1">
            <div><span className="text-[var(--color-admin-primary)] font-bold">HISTORICAL BACKTEST</span> — Replays actual trigger events from the DB against a synthetic rider cohort. Use to validate premium adequacy over real weather periods.</div>
            <div><span className="text-yellow-400 font-bold">STRESS SCENARIO</span> — Models a single catastrophic trigger event. Use to check if reserve buffer can absorb worst-case payouts.</div>
            <div><span className="text-[var(--color-admin-text)]/50 font-bold">LOSS RATIO</span> — Target range: 0.55–0.70 (adequate). Above 0.85 = premium increase needed. Below 0.40 = room to expand coverage.</div>
          </div>
        </div>
      </div>
    </AdminInstantLoad>
  );
}