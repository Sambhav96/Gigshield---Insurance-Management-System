import {
  AdminDashboardResponse,
  LiveDashboardResponse,
  PolicyResponse,
  PolicyQuote,
  TriggerInfo,
} from "./types";

export interface PolicyDisplayData {
  id: string;
  rider_id: string;
  hub_id: string;
  plan: string;
  plan_name: string;
  status: string;
  coverage_pct: number;
  coveragePct: number;
  weekly_premium: number;
  premiumAmount: number;
  plan_cap_multiplier: number;
  capMultiplier: number;
  discount_weeks: number;
  discountWeeks: number;
  weekly_payout_used: number;
  weeklyPayoutUsed: number;
}

export interface RiderHomeData {
  activeTrigger: TriggerInfo | null;
  weeklyRemaining: number;
  expectedPayoutNow: number;
  muLabel: string;
  policyStatus: string;
  discountWeeks: number;
  nextDebit: string;
}

export interface AdminOverviewData {
  activePolicies: number;
  payoutsTodayCount: number;
  payoutsTodayInr: number;
  pendingClaims: number;
  activeTriggers: number;
  lossRatio7d: number;
  liquidity: object;
  circuitBreakers: Record<string, string>;
  killSwitch: string;
}

function normalizePlanName(input: unknown, fallback = "Standard"): string {
  const raw = typeof input === "string" ? input.trim() : "";
  if (!raw) return fallback;
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

export function adaptPolicyResponse(raw: PolicyResponse): PolicyDisplayData {
  const normalizedPlan = typeof raw?.plan === "string" && raw.plan.trim() ? raw.plan : "standard";
  const titlePlan = normalizePlanName(raw?.plan, "Standard");

  return {
    id: raw.id,
    rider_id: raw.rider_id,
    hub_id: raw.hub_id,
    plan: normalizedPlan,
    plan_name: titlePlan,
    status: raw.status,
    coverage_pct: raw.coverage_pct,
    coveragePct: raw.coverage_pct,
    weekly_premium: raw.weekly_premium,
    premiumAmount: raw.weekly_premium,
    plan_cap_multiplier: raw.plan_cap_multiplier,
    capMultiplier: raw.plan_cap_multiplier,
    discount_weeks: raw.discount_weeks,
    discountWeeks: raw.discount_weeks,
    weekly_payout_used: raw.weekly_payout_used,
    weeklyPayoutUsed: raw.weekly_payout_used,
  };
}

export function adaptLiveDashboard(raw: LiveDashboardResponse): RiderHomeData {
  return {
    activeTrigger: raw.active_trigger,
    weeklyRemaining: raw.weekly_remaining,
    expectedPayoutNow: raw.expected_payout_now,
    muLabel: raw.mu_label,
    policyStatus: raw.policy_status,
    discountWeeks: raw.discount_weeks,
    nextDebit: raw.next_debit,
  };
}

export function adaptAdminDashboard(raw: AdminDashboardResponse): AdminOverviewData {
  return {
    activePolicies: raw.kpis.active_policies,
    payoutsTodayCount: raw.kpis.payouts_today_count,
    payoutsTodayInr: raw.kpis.payouts_today_inr,
    pendingClaims: raw.kpis.pending_claims,
    activeTriggers: raw.kpis.active_triggers,
    lossRatio7d: raw.kpis.loss_ratio_7d,
    liquidity: raw.liquidity,
    circuitBreakers: raw.circuit_breakers,
    killSwitch: raw.kill_switch,
  };
}

export function adaptPolicyQuoteResponse(raw: any): PolicyQuote {
  const planName = typeof raw?.plan_name === "string" && raw.plan_name.trim()
    ? raw.plan_name
    : (typeof raw?.plan === "string" && raw.plan.trim() ? raw.plan : "standard");
  const premium = Number(raw?.premium_amount ?? raw?.weekly_premium ?? raw?.p_final ?? 0);
  const coveragePctRaw = Number(raw?.coverage_percent ?? raw?.coverage_pct ?? 0);
  const coveragePct = coveragePctRaw <= 1 ? Math.round(coveragePctRaw * 100) : coveragePctRaw;

  return {
    plan_name: normalizePlanName(planName, "Standard"),
    premium_amount: premium,
    coverage_percent: coveragePct,
    weekly_cap: Number(raw?.weekly_cap ?? 0),
    covered_triggers: (raw?.covered_triggers || raw?.triggers_covered || []) as string[],
    quote_explanation: (raw?.quote_explanation || "Real-time quote calculated from live risk inputs.") as string,
  };
}
