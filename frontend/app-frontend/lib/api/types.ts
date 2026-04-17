export interface ApiError {
  code: string;
  message: string;
  fieldErrs?: Record<string, string>;
}

export interface ApiResponse<T> {
  data: T | null;
  error: ApiError | null;
  status: number;
}

export interface PaginatedData<T> {
  items: T[];
  total: number;
  page: number;
  pages: number;
}

export interface AuthUser {
  id: string;
  email: string;
  role: 'rider' | 'hub' | 'admin';
}

export interface RiderProfile {
  id?: string;
  user_id?: string;
  name: string;
  phone: string;
  platform: string;
  city: string;
  declared_income: number;
  hub_id: string;
}

export interface PolicyData {
  id?: string;
  rider_id?: string;
  status: 'active' | 'pending' | 'expired';
  plan_name: string;
  hub_id: string;
  premium_amount: number;
}

export interface PolicyQuote {
  plan_name: string;
  premium_amount: number;
  coverage_percent: number;
  weekly_cap: number;
  covered_triggers: string[];
  quote_explanation: string;
}

export interface AuthTokenResponse {
  access_token: string;
  rider_id?: string;
  admin_id?: string;
  hub_manager_id?: string;
  is_new_rider?: boolean;
}

export interface RiderProfileResponse {
  id: string;
  name: string;
  phone: string;
  platform: string;
  city: string;
  declared_income: number;
  effective_income: number;
  tier: string;
  risk_score: number;
  risk_profile: string;
  phone_verified: boolean;
  experiment_group_id: string;
  razorpay_fund_account_id?: string | null;
  hub_id?: string | null;
}

export interface PolicyResponse {
  id: string;
  rider_id: string;
  plan: string;
  status: string;
  coverage_pct: number;
  weekly_premium: number;
  plan_cap_multiplier: number;
  discount_weeks: number;
  hub_id: string;
  weekly_payout_used: number;
}

export interface TriggerInfo {
  type: string;
  duration_mins: number;
  paid_so_far: number;
  event_cap_remaining: number;
  trigger_id: string;
}

export interface LiveDashboardResponse {
  active_trigger: TriggerInfo | null;
  weekly_remaining: number;
  expected_payout_now: number;
  mu_label: string;
  policy_status: string;
  discount_weeks: number;
  next_debit: string;
}

export interface ClaimResponse {
  id: string;
  rider_id: string;
  trigger_id: string;
  status: string;
  fraud_score: number;
  event_payout: number;
  actual_payout: number;
  initiated_at: string;
  duration_hrs: number;
}

export interface AdminKPIs {
  active_policies: number;
  payouts_today_count: number;
  payouts_today_inr: number;
  pending_claims: number;
  active_triggers: number;
  loss_ratio_7d: number;
}

export interface AdminDashboardResponse {
  kpis: AdminKPIs;
  liquidity: object;
  circuit_breakers: Record<string, string>;
  kill_switch: string;
}

export interface HubMetricsResponse {
  active_riders: number;
  open_incidents: number;
  risk_quotient: number;
  hub_name: string;
}

export interface FleetRider {
  rider_id: string;
  name: string;
  status: string;
  last_location: string;
  policy_plan: string;
  coverage_cap: number;
  is_on_shift: boolean;
}

export interface HubIncident {
  id: string;
  trigger_type: string;
  triggered_at: string;
  status: string;
  affected_rider_count: number;
  oracle_score: number;
}
