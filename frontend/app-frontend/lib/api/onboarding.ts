import { fetchApi, riderPath } from "./client";
import { ApiResponse, PolicyData, PolicyResponse, RiderProfile, RiderProfileResponse } from "./types";
import { adaptPolicyQuoteResponse, adaptPolicyResponse } from "./adapters";

/**
 * Onboarding service backed by live API calls.
 * Local browser storage keys used for integration state:
 *   gs_rider_id
 *   gs_hub_id
 *   gs_fund_account_id
 *   gs_policy_id
 */
export const onboardingService = {
  // ── Profile ──────────────────────────────────────────────────────

  /**
   * POST /api/v1/riders
   * Body: { name, phone, platform, city, declared_income, hub_id }
   */
  createRiderProfile: async (profile: RiderProfile): Promise<ApiResponse<{ rider_id: string; status: string }>> => {
    const payload = {
      name: profile.name,
      phone: profile.phone,
      platform: profile.platform.toLowerCase(),
      city: profile.city,
      declared_income: Number(profile.declared_income),
      hub_id: profile.hub_id,
    };

    // First try POST /riders (new phone-based rider)
    const res = await fetchApi<{ rider_id: string; status: string }>(riderPath("/riders"), {
      method: "POST",
      body: JSON.stringify(payload),
    });

    // 409 = rider already registered via email (/auth/register) — update profile instead
    if (res.status === 409 || (res.error?.code === "409")) {
      const patchRes = await fetchApi<{ status: string; id: string; hub_id: string }>(riderPath("/riders/me/profile"), {
        method: "PATCH",
        body: JSON.stringify({
          name: profile.name,
          phone: profile.phone,
          platform: profile.platform.toLowerCase(),
          city: profile.city,
          declared_income: Number(profile.declared_income),
          hub_id: profile.hub_id,
        }),
      });
      if (!patchRes.error && patchRes.data) {
        const riderId = patchRes.data.id;
        if (typeof window !== "undefined") {
          localStorage.setItem("gs_rider_id", riderId);
          localStorage.setItem("gs_hub_id", profile.hub_id);
        }
        return { data: { rider_id: riderId, status: "updated" }, error: null, status: 200 };
      }
      return { data: null, error: patchRes.error, status: patchRes.status };
    }

    if (!res.error && res.data && typeof window !== "undefined") {
      localStorage.setItem("gs_rider_id", res.data.rider_id);
      localStorage.setItem("gs_hub_id", profile.hub_id);
    }

    return res;
  },

  /**
   * GET /api/v1/riders/me
   */
  getRiderProfile: async (): Promise<ApiResponse<RiderProfile>> => {
    const res = await fetchApi<RiderProfileResponse & { hub_id?: string | null }>(riderPath("/riders/me"), {
      method: "GET",
    });

    if (res.error || !res.data) {
      return { data: null, error: res.error, status: res.status };
    }

    const platformRaw = (res.data.platform || "").toLowerCase();
    const normalizedPlatform = platformRaw ? platformRaw.charAt(0).toUpperCase() + platformRaw.slice(1) : "";
    const resolvedHubId = (res.data as any).hub_id || (typeof window !== "undefined" ? localStorage.getItem("gs_hub_id") : "") || "";

    if (typeof window !== "undefined") {
      localStorage.setItem("gs_rider_id", res.data.id);
      if (resolvedHubId) localStorage.setItem("gs_hub_id", resolvedHubId);
    }

    return {
      data: {
        id: res.data.id,
        name: res.data.name,
        phone: res.data.phone,
        platform: normalizedPlatform,
        city: res.data.city,
        declared_income: Number(res.data.declared_income),
        hub_id: resolvedHubId,
      },
      error: null,
      status: res.status,
    };
  },

  // ── Hubs ─────────────────────────────────────────────────────────

  /**
   * GET /api/v1/hubs?city={city}
   */
  searchHubs: async (city: string): Promise<ApiResponse<{ id: string; name: string }[]>> => {
    const res = await fetchApi<{ hubs: Array<{ id: string; name: string; city?: string }> }>(
      riderPath(`/hubs?city=${encodeURIComponent(city)}`),
      { method: "GET" }
    );

    if (res.error || !res.data) {
      return { data: null, error: res.error, status: res.status };
    }

    return {
      data: (res.data.hubs || []).map((hub) => ({ id: hub.id, name: hub.name })),
      error: null,
      status: res.status,
    };
  },

  // ── Policy Quotes ─────────────────────────────────────────────────

  /**
   * GET /api/v1/policies/quote?plan={plan}&hub_id={hub_id}
   * Returns a PolicyQuote object per backend contract.
   */
  getPolicyQuote: async (plan: string, hub_id: string): Promise<ApiResponse<{
    plan_name: string;
    premium_amount: number;
    coverage_percent: number;
    weekly_cap: number;
    covered_triggers: string[];
    quote_explanation: string;
  }>> => {
    const res = await fetchApi<any>(
      riderPath(`/policies/quote?plan=${encodeURIComponent(plan.toLowerCase())}&hub_id=${encodeURIComponent(hub_id)}`),
      { method: "GET" }
    );

    if (res.error || !res.data) {
      return { data: null, error: res.error, status: res.status };
    }

    return { data: adaptPolicyQuoteResponse(res.data), error: null, status: res.status };
  },

  // ── Policy Creation ───────────────────────────────────────────────

  /**
   * POST /api/v1/policies
   * Body: { plan_name, hub_id, razorpay_fund_account_id }
   */
  createPolicy: async (data: {
    plan_name: string;
    hub_id: string;
    razorpay_fund_account_id: string;
  }): Promise<ApiResponse<PolicyData>> => {
    const fundAccountId = typeof window !== "undefined"
      ? localStorage.getItem("gs_fund_account_id") || ""
      : "";

    const res = await fetchApi<PolicyResponse>(riderPath("/policies"), {
      method: "POST",
      body: JSON.stringify({
        plan: data.plan_name.toLowerCase(),
        hub_id: data.hub_id,
        razorpay_fund_account_id: fundAccountId,
      }),
    });

    if (res.error || !res.data) {
      return { data: null, error: res.error, status: res.status };
    }

    const adapted = adaptPolicyResponse(res.data);
    if (typeof window !== "undefined") {
      localStorage.setItem("gs_policy_id", adapted.id);
    }

    return {
      data: {
        id: adapted.id,
        rider_id: adapted.rider_id,
        status: adapted.status as PolicyData["status"],
        plan_name: adapted.plan_name,
        hub_id: adapted.hub_id,
        premium_amount: adapted.premiumAmount,
      },
      error: null,
      status: res.status,
    };
  },

  /**
   * GET /api/v1/policies/me
   */
  getPolicy: async (): Promise<ApiResponse<PolicyData>> => {
    const res = await fetchApi<PolicyResponse>(riderPath("/policies/me"), {
      method: "GET",
    });

    if (res.error || !res.data) {
      return { data: null, error: res.error, status: res.status };
    }

    const adapted = adaptPolicyResponse(res.data);
    if (typeof window !== "undefined") {
      localStorage.setItem("gs_policy_id", adapted.id);
    }

    return {
      data: {
        id: adapted.id,
        rider_id: adapted.rider_id,
        status: adapted.status as PolicyData["status"],
        plan_name: adapted.plan_name,
        hub_id: adapted.hub_id,
        premium_amount: adapted.premiumAmount,
      },
      error: null,
      status: res.status,
    };
  },
};
