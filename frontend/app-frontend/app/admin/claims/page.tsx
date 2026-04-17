"use client";

import { AdminInstantLoad } from "@/lib/motion/safeWrappers";
import { useEffect, useState, useCallback } from "react";
import { fetchApi, adminPath } from "@/lib/api/client";

const STATUS_COLORS: Record<string, string> = {
  auto_cleared:    "text-[var(--color-admin-primary)] border-[var(--color-admin-primary)]/30 bg-[var(--color-admin-primary)]/5",
  paid:            "text-[#10b981] border-[#10b981]/30 bg-[#10b981]/5",
  manual_approved: "text-[#10b981] border-[#10b981]/30 bg-[#10b981]/5",
  soft_flagged:    "text-yellow-400 border-yellow-400/30 bg-yellow-400/5",
  hard_flagged:    "text-orange-400 border-orange-400/30 bg-orange-400/5",
  manual_review:   "text-orange-400 border-orange-400/30 bg-orange-400/5",
  manual_rejected: "text-[var(--color-admin-error)] border-[var(--color-admin-error)]/30 bg-[var(--color-admin-error)]/5",
  rejected:        "text-[var(--color-admin-error)] border-[var(--color-admin-error)]/30 bg-[var(--color-admin-error)]/5",
  evaluating:      "text-[var(--color-admin-text)]/50 border-[var(--color-admin-outline)]/20",
  initiated:       "text-[var(--color-admin-text)]/50 border-[var(--color-admin-outline)]/20",
  cap_exhausted:   "text-purple-400 border-purple-400/30 bg-purple-400/5",
  disputed:        "text-purple-400 border-purple-400/30 bg-purple-400/5",
};

const STATUS_FILTERS = ["all", "hard_flagged", "manual_review", "soft_flagged", "auto_cleared", "paid", "manual_rejected", "disputed"];

export default function AdminClaims() {
  const [claims, setClaims] = useState<any[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [selectedClaim, setSelectedClaim] = useState<any | null>(null);
  const [adjustAmount, setAdjustAmount] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [actionMsg, setActionMsg] = useState<{ id: string; ok: boolean; text: string } | null>(null);

  const loadClaims = useCallback(async (targetPage: number, status: string) => {
    setIsLoading(true);
    setError(null);
    const qs = status === "all" ? `page=${targetPage}` : `page=${targetPage}&status=${status}`;
    const res = await fetchApi<{ items: any[]; total: number; page: number }>(adminPath(`/admin/claims?${qs}`), { method: "GET" });
    if (res.error || !res.data) {
      setError(res.error?.message || "Unable to load claims");
      setClaims([]);
      setTotal(0);
    } else {
      setClaims(res.data.items || []);
      setTotal(res.data.total || 0);
    }
    setIsLoading(false);
  }, []);

  useEffect(() => { loadClaims(page, statusFilter); }, [page, statusFilter, loadClaims]);

  const runAction = async (claimId: string, action: "approve" | "reject" | "approve_partial" | "escalate", extra?: { reason?: string; amount?: number }) => {
    setActionLoading(claimId);
    const body: any = { action };
    if (extra?.reason) body.reason = extra.reason;
    if (extra?.amount) body.amount = extra.amount;

    const res = await fetchApi<{ status: string }>(adminPath(`/admin/claims/${claimId}/action`), {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (res.error) {
      setActionMsg({ id: claimId, ok: false, text: res.error.message || "Action failed" });
    } else {
      setActionMsg({ id: claimId, ok: true, text: `${action.toUpperCase()} applied` });
      setTimeout(() => setActionMsg(null), 3000);
      await loadClaims(page, statusFilter);
      setSelectedClaim(null);
    }
    setActionLoading(null);
  };

  const fraudColor = (score: number) =>
    score >= 0.80 ? "text-[var(--color-admin-error)]" :
    score >= 0.40 ? "text-yellow-400" : "text-[var(--color-admin-primary)]";

  const pages = Math.max(1, Math.ceil(total / 20));

  return (
    <AdminInstantLoad>
      <div className="w-full h-full flex flex-col min-h-0">
        {isLoading && (
          <div className="fixed inset-0 z-[999] bg-[var(--color-admin-bg)]/80 flex items-center justify-center">
            <span className="material-symbols-outlined animate-spin text-[var(--color-admin-primary)] text-4xl">autorenew</span>
          </div>
        )}

        {/* Header */}
        <div className="border-b border-[var(--color-admin-outline)]/30 px-5 py-3 flex items-center justify-between bg-[var(--color-admin-surface-high)] shrink-0">
          <h3 className="text-[10px] font-['JetBrains_Mono'] font-bold tracking-widest uppercase text-[var(--color-admin-primary)]">
            Claims Database · {total} records
          </h3>
          <button onClick={() => loadClaims(page, statusFilter)}
            className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 hover:text-white uppercase border border-[var(--color-admin-outline)]/20 px-2 py-1 hover:border-[var(--color-admin-outline)]/50 transition-colors">
            REFRESH
          </button>
        </div>

        {/* Status filter tabs */}
        <div className="border-b border-[var(--color-admin-outline)]/20 px-5 py-2 flex gap-1.5 overflow-x-auto shrink-0">
          {STATUS_FILTERS.map(s => (
            <button key={s} onClick={() => { setStatusFilter(s); setPage(1); }}
              className={`text-[9px] font-['JetBrains_Mono'] uppercase px-2.5 py-1 border whitespace-nowrap transition-colors ${
                statusFilter === s
                  ? "border-[var(--color-admin-primary)]/50 bg-[var(--color-admin-primary)]/10 text-[var(--color-admin-primary)]"
                  : "border-[var(--color-admin-outline)]/20 text-[var(--color-admin-text)]/40 hover:text-white"
              }`}>{s.replace(/_/g, " ")}</button>
          ))}
        </div>

        {error && (
          <div className="mx-5 my-2 bg-[var(--color-admin-error)]/10 border border-[var(--color-admin-error)]/30 text-[var(--color-admin-error)] text-[10px] font-['JetBrains_Mono'] px-3 py-2">{error}</div>
        )}

        {/* Table */}
        <div className="flex-1 overflow-auto custom-scrollbar">
          <table className="w-full text-left text-xs font-['Inter'] whitespace-nowrap">
            <thead className="bg-[var(--color-admin-bg)] font-['JetBrains_Mono'] text-[9px] text-[var(--color-admin-text)]/40 tracking-widest uppercase sticky top-0 border-b border-[var(--color-admin-outline)]/30 z-10">
              <tr>
                <th className="px-5 py-3">CLAIM_ID</th>
                <th className="px-5 py-3">RIDER</th>
                <th className="px-5 py-3">TRIGGER</th>
                <th className="px-5 py-3">FILED</th>
                <th className="px-5 py-3">PAYOUT</th>
                <th className="px-5 py-3">FRAUD_SCORE</th>
                <th className="px-5 py-3">STATUS</th>
                <th className="px-5 py-3 text-right">ACTIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-admin-outline)]/10 text-[var(--color-admin-text)]/80">
              {claims.length === 0 && !isLoading ? (
                <tr><td colSpan={8} className="px-5 py-8 text-center text-[var(--color-admin-text)]/30 font-['JetBrains_Mono'] text-[10px] uppercase">No claims found for filter: {statusFilter}</td></tr>
              ) : (
                claims.map(c => {
                  const fs = Number(c.fraud_score || 0);
                  const statusCls = STATUS_COLORS[c.status] || "text-[var(--color-admin-text)]/50 border-[var(--color-admin-outline)]/20";
                  const isActioning = actionLoading === c.id;
                  const needsAction = ["hard_flagged", "manual_review", "soft_flagged"].includes(c.status);
                  const msg = actionMsg?.id === c.id ? actionMsg : null;

                  return (
                    <tr key={c.id} onClick={() => setSelectedClaim(c === selectedClaim ? null : c)}
                      className={`hover:bg-[var(--color-admin-surface-high)] transition-colors cursor-pointer ${selectedClaim?.id === c.id ? "bg-[var(--color-admin-surface-high)]" : ""}`}>
                      <td className="px-5 py-3.5 font-['JetBrains_Mono'] text-[var(--color-admin-primary)] text-[10px]">
                        {String(c.id).slice(0,8).toUpperCase()}
                      </td>
                      <td className="px-5 py-3.5 font-medium text-white max-w-[100px] truncate">{c.rider_name || String(c.rider_id).slice(0,8)}</td>
                      <td className="px-5 py-3.5">
                        <span className="text-[9px] font-['JetBrains_Mono'] uppercase text-[var(--color-admin-text)]/60">{c.trigger_type || "—"}</span>
                      </td>
                      <td className="px-5 py-3.5 font-['JetBrains_Mono'] text-[10px] text-[var(--color-admin-text)]/50">
                        {c.initiated_at ? new Date(c.initiated_at).toLocaleDateString("en-IN", { day:"2-digit", month:"short" }) : "--"}
                      </td>
                      <td className="px-5 py-3.5 font-['JetBrains_Mono'] text-[10px]">
                        ₹{Number(c.event_payout || c.actual_payout || 0).toLocaleString("en-IN")}
                      </td>
                      <td className="px-5 py-3.5 font-['JetBrains_Mono'] text-[10px]">
                        <span className={fraudColor(fs)}>{fs.toFixed(3)}</span>
                      </td>
                      <td className="px-5 py-3.5">
                        <span className={`text-[9px] font-['JetBrains_Mono'] font-bold border px-1.5 py-0.5 ${statusCls}`}>
                          {String(c.status || "—").replace(/_/g," ").toUpperCase()}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-right">
                        {msg ? (
                          <span className={`text-[9px] font-['JetBrains_Mono'] ${msg.ok ? "text-[var(--color-admin-primary)]" : "text-[var(--color-admin-error)]"}`}>{msg.text}</span>
                        ) : needsAction ? (
                          <div className="flex items-center gap-1.5 justify-end" onClick={e => e.stopPropagation()}>
                            <button onClick={() => runAction(c.id, "approve")} disabled={isActioning}
                              className="text-[9px] font-['JetBrains_Mono'] px-2 py-1 border border-[var(--color-admin-primary)]/30 text-[var(--color-admin-primary)] hover:bg-[var(--color-admin-primary)]/10 disabled:opacity-50 transition-colors uppercase">
                              {isActioning ? "..." : "APPROVE"}
                            </button>
                            <button onClick={() => runAction(c.id, "reject", { reason: rejectReason || "admin_review" })} disabled={isActioning}
                              className="text-[9px] font-['JetBrains_Mono'] px-2 py-1 border border-[var(--color-admin-error)]/30 text-[var(--color-admin-error)] hover:bg-[var(--color-admin-error)]/10 disabled:opacity-50 transition-colors uppercase">
                              REJECT
                            </button>
                          </div>
                        ) : (
                          <span className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/20">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Expanded claim detail panel */}
        {selectedClaim && (
          <div className="border-t border-[var(--color-admin-outline)]/30 bg-[var(--color-admin-surface-high)] px-5 py-4 shrink-0 space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-[10px] font-['JetBrains_Mono'] font-bold uppercase text-[var(--color-admin-primary)]">
                CLAIM DETAIL · {String(selectedClaim.id).slice(0,8).toUpperCase()}
              </h4>
              <button onClick={() => setSelectedClaim(null)} className="text-[var(--color-admin-text)]/30 hover:text-white">
                <span className="material-symbols-outlined text-base">close</span>
              </button>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3 text-[9px] font-['JetBrains_Mono']">
              {[
                ["Oracle Confidence", selectedClaim.oracle_confidence],
                ["Presence Confidence", selectedClaim.presence_confidence],
                ["Duration hrs", selectedClaim.duration_hrs],
                ["MU Time", selectedClaim.mu_time],
                ["Admin Note", selectedClaim.admin_note || "—"],
                ["Explanation", selectedClaim.explanation_text?.slice(0,40) || "—"],
              ].map(([k, v]) => (
                <div key={String(k)}>
                  <div className="text-[var(--color-admin-text)]/30 uppercase mb-0.5">{k}</div>
                  <div className="text-white">{v != null ? String(v) : "—"}</div>
                </div>
              ))}
            </div>

            {/* Partial adjust form */}
            {["hard_flagged","manual_review","soft_flagged"].includes(selectedClaim.status) && (
              <div className="flex items-center gap-3 pt-2 border-t border-[var(--color-admin-outline)]/20" onClick={e => e.stopPropagation()}>
                <span className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 uppercase">Partial adjust ₹:</span>
                <input type="number" value={adjustAmount} onChange={e => setAdjustAmount(e.target.value)}
                  placeholder="0.00"
                  className="bg-[var(--color-admin-bg)] border border-[var(--color-admin-outline)]/30 px-2 py-1 text-[10px] font-['JetBrains_Mono'] text-white w-24 focus:outline-none focus:border-[var(--color-admin-primary)]/50" />
                <button disabled={!adjustAmount || actionLoading === selectedClaim.id}
                  onClick={() => runAction(selectedClaim.id, "approve_partial", { amount: Number(adjustAmount) })}
                  className="text-[9px] font-['JetBrains_Mono'] px-2 py-1 border border-yellow-400/30 text-yellow-400 hover:bg-yellow-400/10 disabled:opacity-50 uppercase transition-colors">
                  ADJUST & APPROVE
                </button>
                <span className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/40 uppercase">Reject reason:</span>
                <input value={rejectReason} onChange={e => setRejectReason(e.target.value)}
                  placeholder="policy_violation"
                  className="bg-[var(--color-admin-bg)] border border-[var(--color-admin-outline)]/30 px-2 py-1 text-[10px] font-['JetBrains_Mono'] text-white w-36 focus:outline-none focus:border-[var(--color-admin-error)]/50" />
              </div>
            )}
          </div>
        )}

        {/* Pagination */}
        <div className="border-t border-[var(--color-admin-outline)]/30 px-5 py-2 flex items-center justify-between text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-text)]/50 shrink-0">
          <span>RECORDS: {total} · PAGE {page}/{pages}</span>
          <div className="flex gap-1.5">
            <button disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}
              className="px-2 py-1 border border-[var(--color-admin-outline)]/30 disabled:opacity-30 hover:text-white hover:border-[var(--color-admin-outline)]/60 uppercase transition-colors">PREV</button>
            {[...Array(Math.min(5, pages))].map((_, i) => {
              const p = Math.max(1, Math.min(pages - 4, page - 2)) + i;
              return (
                <button key={p} onClick={() => setPage(p)}
                  className={`px-2 py-1 border uppercase transition-colors ${p === page ? "border-[var(--color-admin-primary)]/50 text-[var(--color-admin-primary)]" : "border-[var(--color-admin-outline)]/30 hover:text-white"}`}>
                  {p}
                </button>
              );
            })}
            <button disabled={page >= pages} onClick={() => setPage(p => Math.min(pages, p + 1))}
              className="px-2 py-1 border border-[var(--color-admin-outline)]/30 disabled:opacity-30 hover:text-white hover:border-[var(--color-admin-outline)]/60 uppercase transition-colors">NEXT</button>
          </div>
        </div>
      </div>
    </AdminInstantLoad>
  );
}