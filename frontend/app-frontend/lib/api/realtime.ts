/**
 * lib/api/realtime.ts — Supabase Realtime subscriptions
 *
 * Replaces 30-second polling with live postgres_changes subscriptions.
 * Supabase URL and anon key are already in .env → NEXT_PUBLIC_SUPABASE_URL
 *
 * Setup: set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in .env.local
 * These map to the existing SUPABASE_URL/SUPABASE_ANON_KEY in backend .env.
 */

type RealtimeCallback = (payload: any) => void;

let supabaseClient: any = null;

function getSupabase() {
  if (supabaseClient) return supabaseClient;

  const url  = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key  = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !key || url.includes("placeholder")) {
    return null;
  }

  try {
    const { createClient } = require("@supabase/supabase-js");
    supabaseClient = createClient(url, key);
    return supabaseClient;
  } catch {
    return null;
  }
}

/**
 * Subscribe to trigger_events changes for a given H3 index.
 * Falls back gracefully if Supabase Realtime not configured.
 * Returns an unsubscribe function.
 */
export function subscribeToTriggerEvents(
  h3Index: string,
  onInsert: RealtimeCallback,
  onUpdate: RealtimeCallback,
): () => void {
  const sb = getSupabase();
  if (!sb) {
    // Silently no-op; polling will handle updates
    return () => {};
  }

  const channel = sb
    .channel(`trigger_events_${h3Index}`)
    .on(
      "postgres_changes",
      {
        event: "INSERT",
        schema: "public",
        table: "trigger_events",
        filter: `h3_index=eq.${h3Index}`,
      },
      (payload: any) => onInsert(payload.new)
    )
    .on(
      "postgres_changes",
      {
        event: "UPDATE",
        schema: "public",
        table: "trigger_events",
        filter: `h3_index=eq.${h3Index}`,
      },
      (payload: any) => onUpdate(payload.new)
    )
    .subscribe();

  return () => {
    try {
      sb.removeChannel(channel);
    } catch { /* ignore */ }
  };
}

/**
 * Subscribe to claims changes for a given rider.
 * Fires when a claim is paid or status changes — rider sees update instantly.
 */
export function subscribeToRiderClaims(
  riderId: string,
  onStatusChange: RealtimeCallback,
): () => void {
  const sb = getSupabase();
  if (!sb) return () => {};

  const channel = sb
    .channel(`claims_rider_${riderId}`)
    .on(
      "postgres_changes",
      {
        event: "UPDATE",
        schema: "public",
        table: "claims",
        filter: `rider_id=eq.${riderId}`,
      },
      (payload: any) => {
        // Only fire callback on meaningful status transitions
        const newStatus = payload.new?.status;
        const oldStatus = payload.old?.status;
        if (newStatus && newStatus !== oldStatus) {
          onStatusChange(payload.new);
        }
      }
    )
    .subscribe();

  return () => {
    try { sb.removeChannel(channel); } catch { /* ignore */ }
  };
}

/**
 * Subscribe to payouts for a given rider.
 * Fires instantly when a payout is inserted — rider sees "Payout Sent" in <1s.
 */
export function subscribeToRiderPayouts(
  riderId: string,
  onPayout: RealtimeCallback,
): () => void {
  const sb = getSupabase();
  if (!sb) return () => {};

  const channel = sb
    .channel(`payouts_rider_${riderId}`)
    .on(
      "postgres_changes",
      {
        event: "INSERT",
        schema: "public",
        table: "payouts",
        filter: `rider_id=eq.${riderId}`,
      },
      (payload: any) => onPayout(payload.new)
    )
    .subscribe();

  return () => {
    try { sb.removeChannel(channel); } catch { /* ignore */ }
  };
}

/** Check if Supabase Realtime is configured and available. */
export function isRealtimeAvailable(): boolean {
  return getSupabase() !== null;
}
