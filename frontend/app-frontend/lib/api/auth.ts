/**
 * auth.ts — GigShield authentication service
 *
 * FIXES APPLIED:
 * - CRITICAL-05: Separate token namespaces: gs_rider_token, gs_admin_token, gs_hub_token
 * - BUG-1 (Hub login): Removed premature 404/503 early-return; hub login now fully wired
 * - BUG-2 (Rider redirect loop): Removed fragile gs_fund_account_id localStorage check
 *   from auth layer; onboarding state now determined by backend only
 * - BUG-3 (Admin portal): Admin token stored under gs_admin_token, not gs_rider_token
 * - Added consistent logout() that clears ALL token namespaces
 */
import { fetchApi, riderPath, TOKEN_KEYS } from "./client";
import { ApiResponse, AuthTokenResponse, AuthUser } from "./types";

const USER_KEYS = {
  rider: "gs_rider_user",
  admin: "gs_admin_user",
  hub:   "gs_hub_user",
} as const;

const ONBOARDING_REQUIRED_KEY = "gs_onboarding_required";

// ── Generic store factory ──────────────────────────────────────────────────────

function makeStore(tokenKey: string, userKey: string) {
  return {
    save(token: string, user: AuthUser) {
      if (typeof window === "undefined") return;
      localStorage.setItem(tokenKey, token);
      localStorage.setItem(userKey, JSON.stringify(user));
    },
    clear() {
      if (typeof window === "undefined") return;
      localStorage.removeItem(tokenKey);
      localStorage.removeItem(userKey);
      sessionStorage.removeItem(tokenKey);
      sessionStorage.removeItem(userKey);
    },
    getToken(): string | null {
      if (typeof window === "undefined") return null;
      return localStorage.getItem(tokenKey) || sessionStorage.getItem(tokenKey);
    },
    getUser(): AuthUser | null {
      if (typeof window === "undefined") return null;
      const raw = localStorage.getItem(userKey) || sessionStorage.getItem(userKey);
      if (!raw) return null;
      try { return JSON.parse(raw); } catch { return null; }
    },
  };
}

const riderStore = makeStore(TOKEN_KEYS.rider, USER_KEYS.rider);
const adminStore = makeStore(TOKEN_KEYS.admin, USER_KEYS.admin);
const hubStore   = makeStore(TOKEN_KEYS.hub,   USER_KEYS.hub);

// ── Legacy export for RiderRouteGuard compatibility ────────────────────────────
export const tokenStore = {
  save:     riderStore.save.bind(riderStore),
  clear:    () => { riderStore.clear(); adminStore.clear(); hubStore.clear(); },
  getToken: riderStore.getToken.bind(riderStore),
  getUser:  riderStore.getUser.bind(riderStore),
  getRole(): string | null {
    // Check all stores in priority order
    for (const store of [riderStore, adminStore, hubStore]) {
      const token = store.getToken();
      if (!token) continue;
      try {
        const parts = token.split(".");
        if (parts.length < 2) continue;
        const pad = parts[1].replace(/-/g, "+").replace(/_/g, "/");
        const decoded = atob(pad + "=".repeat((4 - (pad.length % 4)) % 4));
        const payload = JSON.parse(decoded);
        if (typeof payload?.role === "string") return payload.role;
      } catch { /* ignore */ }
    }
    return null;
  },
};

// ── JWT helpers ────────────────────────────────────────────────────────────────

function decodeTokenPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length < 2) return null;
    const pad = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(atob(pad + "=".repeat((4 - (pad.length % 4)) % 4)));
  } catch { return null; }
}

function isTokenExpired(token: string): boolean {
  const payload = decodeTokenPayload(token);
  if (!payload) return true;
  const exp = Number(payload.exp || 0);
  return !exp || exp <= Date.now() / 1000;
}

// ── Auth service ───────────────────────────────────────────────────────────────

export const authService = {
  // ── Rider register ────────────────────────────────────────────────────────
  registerRider: async (
    email: string,
    password: string
  ): Promise<ApiResponse<{ token: string; user: AuthUser }>> => {
    const res = await fetchApi<AuthTokenResponse>(riderPath("/auth/register"), {
      method: "POST",
      body: JSON.stringify({ email, password, name: "" }),
    });

    if (res.error || !res.data?.access_token || !res.data?.rider_id) {
      return {
        data: null,
        error: res.error || { code: String(res.status), message: "Registration failed" },
        status: res.status,
      };
    }

    const user: AuthUser = { id: res.data.rider_id, email, role: "rider" };
    riderStore.save(res.data.access_token, user);
    // Also persist rider_id for onboarding components
    localStorage.setItem("gs_rider_id", res.data.rider_id);
    localStorage.setItem(ONBOARDING_REQUIRED_KEY, "1");
    return { data: { token: res.data.access_token, user }, error: null, status: res.status || 201 };
  },

  // ── Rider login ───────────────────────────────────────────────────────────
  loginRider: async (
    email: string,
    password: string
  ): Promise<ApiResponse<{ token: string; user: AuthUser }>> => {
    const res = await fetchApi<AuthTokenResponse>(riderPath("/auth/login"), {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });

    if (res.error || !res.data?.access_token || !res.data?.rider_id) {
      return {
        data: null,
        error: res.error || { code: String(res.status), message: "Invalid credentials" },
        status: res.status,
      };
    }

    const user: AuthUser = { id: res.data.rider_id, email, role: "rider" };
    riderStore.save(res.data.access_token, user);
    localStorage.setItem("gs_rider_id", res.data.rider_id);
    // Existing rider login should land on dashboard, not forced onboarding.
    localStorage.removeItem(ONBOARDING_REQUIRED_KEY);
    return { data: { token: res.data.access_token, user }, error: null, status: 200 };
  },

  // ── Hub manager login (BUG-1 FIX: removed premature 404/503 bail-out) ──────
  loginHub: async (
    identifier: string,
    password: string
  ): Promise<ApiResponse<{ token: string; user: AuthUser }>> => {
    // identifier can be either a hub UUID or a username
    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(identifier.trim());
    const body = isUuid
      ? { hub_id: identifier.trim(), password }
      : { username: identifier.trim(), password };

    const res = await fetchApi<AuthTokenResponse>(riderPath("/auth/hub/login"), {
      method: "POST",
      body: JSON.stringify(body),
    });

    if (res.error || !res.data?.access_token) {
      return {
        data: null,
        error: res.error || { code: String(res.status), message: "Hub login failed. Check credentials." },
        status: res.status,
      };
    }

    const hubManagerId = res.data.hub_manager_id || res.data.rider_id || identifier;
    const user: AuthUser = { id: hubManagerId, email: identifier, role: "hub" };
    hubStore.save(res.data.access_token, user);
    if (res.data.hub_id) localStorage.setItem("gs_hub_id", res.data.hub_id);
    return { data: { token: res.data.access_token, user }, error: null, status: res.status || 200 };
  },

  // ── Admin login (BUG-3 FIX: saves to gs_admin_token, not gs_rider_token) ───
  loginAdmin: async (
    username: string,
    password: string
  ): Promise<ApiResponse<{ token: string; user: AuthUser }>> => {
    const res = await fetchApi<AuthTokenResponse>(riderPath("/auth/admin/login"), {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });

    if (res.error || !res.data?.access_token || !res.data?.admin_id) {
      return {
        data: null,
        error: res.error || { code: String(res.status), message: "Admin login failed" },
        status: res.status,
      };
    }

    const user: AuthUser = { id: res.data.admin_id, email: username, role: "admin" };
    adminStore.save(res.data.access_token, user);
    return { data: { token: res.data.access_token, user }, error: null, status: 200 };
  },

  // ── Session verify ────────────────────────────────────────────────────────
  verifySession: (): Promise<ApiResponse<{ user: AuthUser }>> => {
    // Check all stores; return first valid non-expired session
    const checks: Array<{ store: ReturnType<typeof makeStore>; role: string }> = [
      { store: riderStore, role: "rider" },
      { store: adminStore, role: "admin" },
      { store: hubStore,   role: "hub" },
    ];

    for (const { store } of checks) {
      const user = store.getUser();
      const token = store.getToken();
      if (!user || !token) continue;
      if (isTokenExpired(token)) {
        store.clear();
        continue;
      }
      return Promise.resolve({ data: { user }, error: null, status: 200 });
    }

    return Promise.resolve({
      data: null,
      error: { code: "401", message: "No session" },
      status: 401,
    });
  },

  // ── Role-specific session verify ──────────────────────────────────────────
  verifyRiderSession: (): Promise<ApiResponse<{ user: AuthUser }>> => {
    const token = riderStore.getToken();
    const user  = riderStore.getUser();
    if (!token || !user) {
      return Promise.resolve({ data: null, error: { code: "401", message: "No rider session" }, status: 401 });
    }
    if (isTokenExpired(token)) {
      riderStore.clear();
      return Promise.resolve({ data: null, error: { code: "401", message: "Session expired" }, status: 401 });
    }
    if (user.role !== "rider") {
      return Promise.resolve({ data: null, error: { code: "403", message: "Not a rider session" }, status: 403 });
    }
    return Promise.resolve({ data: { user }, error: null, status: 200 });
  },

  verifyAdminSession: (): Promise<ApiResponse<{ user: AuthUser }>> => {
    const token = adminStore.getToken();
    const user  = adminStore.getUser();
    if (!token || !user) {
      return Promise.resolve({ data: null, error: { code: "401", message: "No admin session" }, status: 401 });
    }
    if (isTokenExpired(token)) {
      adminStore.clear();
      return Promise.resolve({ data: null, error: { code: "401", message: "Session expired" }, status: 401 });
    }
    return Promise.resolve({ data: { user }, error: null, status: 200 });
  },

  verifyHubSession: (): Promise<ApiResponse<{ user: AuthUser }>> => {
    const token = hubStore.getToken();
    const user  = hubStore.getUser();
    if (!token || !user) {
      return Promise.resolve({ data: null, error: { code: "401", message: "No hub session" }, status: 401 });
    }
    if (isTokenExpired(token)) {
      hubStore.clear();
      return Promise.resolve({ data: null, error: { code: "401", message: "Session expired" }, status: 401 });
    }
    return Promise.resolve({ data: { user }, error: null, status: 200 });
  },

  // ── Logout (clears all stores) ────────────────────────────────────────────
  logout: () => {
    riderStore.clear();
    adminStore.clear();
    hubStore.clear();
    // Clear legacy keys
    if (typeof window !== "undefined") {
      ["gs_rider_id", "gs_hub_id", "gs_fund_account_id", "gs_policy_id"].forEach(k => {
        localStorage.removeItem(k);
        sessionStorage.removeItem(k);
      });
    }
  },
};
