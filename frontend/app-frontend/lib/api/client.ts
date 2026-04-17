import { ApiResponse } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const RIDER_API_PREFIX = process.env.NEXT_PUBLIC_RIDER_API_PREFIX || "/api/v1";
const ADMIN_API_PREFIX = process.env.NEXT_PUBLIC_ADMIN_API_PREFIX || "/internal";

export type ApiScope = "rider" | "admin" | "hub" | "none";

// ── Token namespace constants (CRITICAL-05 fix: separate namespaces per role) ──
export const TOKEN_KEYS = {
  rider: "gs_rider_token",
  admin: "gs_admin_token",
  hub:   "gs_hub_token",
} as const;

function ensureLeadingSlash(value: string): string {
  return value.startsWith("/") ? value : `/${value}`;
}

function joinPath(prefix: string, endpoint: string): string {
  const normalizedPrefix = prefix.endsWith("/") ? prefix.slice(0, -1) : prefix;
  const normalizedEndpoint = ensureLeadingSlash(endpoint);
  return `${normalizedPrefix}${normalizedEndpoint}`;
}

export function riderPath(endpoint: string): string {
  return joinPath(RIDER_API_PREFIX, endpoint);
}

export function adminPath(endpoint: string): string {
  return joinPath(ADMIN_API_PREFIX, endpoint);
}

export function hubPath(endpoint: string): string {
  return joinPath(RIDER_API_PREFIX, endpoint);
}

export function scopedPath(scope: ApiScope, endpoint: string): string {
  if (scope === "rider") return riderPath(endpoint);
  if (scope === "admin") return adminPath(endpoint);
  if (scope === "hub")   return hubPath(endpoint);
  return ensureLeadingSlash(endpoint);
}

/**
 * Resolve the correct auth token for a given request endpoint.
 * Admin endpoints (/internal/*) use gs_admin_token.
 * Hub endpoints use gs_hub_token if available, rider token as fallback.
 * All other endpoints use gs_rider_token.
 */
function resolveAuthToken(normalizedEndpoint: string): string | null {
  if (typeof window === "undefined") return null;

  const isAdminEndpoint = normalizedEndpoint.startsWith("/internal");
  const isHubEndpoint   = normalizedEndpoint.includes("/hub");

  if (isAdminEndpoint) {
    return (
      localStorage.getItem(TOKEN_KEYS.admin) ||
      sessionStorage.getItem(TOKEN_KEYS.admin) ||
      null
    );
  }

  if (isHubEndpoint) {
    return (
      localStorage.getItem(TOKEN_KEYS.hub) ||
      sessionStorage.getItem(TOKEN_KEYS.hub) ||
      localStorage.getItem(TOKEN_KEYS.rider) ||
      sessionStorage.getItem(TOKEN_KEYS.rider) ||
      null
    );
  }

  // Default: rider token
  return (
    localStorage.getItem(TOKEN_KEYS.rider) ||
    sessionStorage.getItem(TOKEN_KEYS.rider) ||
    null
  );
}

async function parseApiPayload(response: Response): Promise<{ data: unknown; errorMessage?: string }> {
  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");

  if (isJson) {
    const json = await response.json();
    return { data: json };
  }

  const text = await response.text();
  return { data: null, errorMessage: text || "Received non-JSON response from server." };
}

/**
 * Core API wrapper for live FastAPI requests.
 * Automatically injects the correct scoped auth token.
 */
export async function fetchApi<T>(endpoint: string, options?: RequestInit): Promise<ApiResponse<T>> {
  try {
    const normalizedEndpoint = ensureLeadingSlash(endpoint);
    const token = resolveAuthToken(normalizedEndpoint);

    const response = await fetch(`${BASE_URL}${normalizedEndpoint}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options?.headers,
      },
    });

    const parsed = await parseApiPayload(response);

    if (!response.ok) {
      const payload = parsed.data as any;
      const messageFromJson =
        payload?.error?.message || payload?.detail || payload?.message;
      return {
        data: null,
        error: {
          code: String(response.status),
          message:
            messageFromJson ||
            parsed.errorMessage ||
            response.statusText ||
            "Request failed",
        },
        status: response.status,
      };
    }

    const payload = parsed.data as any;
    const result =
      payload && typeof payload === "object" && "data" in payload
        ? (payload.data as T)
        : (payload as T);

    return { data: result, status: response.status, error: null };
  } catch (err: any) {
    return {
      data: null,
      status: 500,
      error: { code: "NETWORK_FAIL", message: err.message || "Failed to reach backend." },
    };
  }
}
