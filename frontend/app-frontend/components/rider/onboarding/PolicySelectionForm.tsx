"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { onboardingService } from "@/lib/api/onboarding";
import { PolicyQuote } from "@/lib/api/types";
import { motion, AnimatePresence } from "framer-motion";

type Phase = "selection" | "activating" | "success" | "error";

function normalizeErrorMessage(input: unknown): string {
  if (typeof input === "string") return input;
  if (Array.isArray(input)) {
    if (input.length === 0) return "Activation failed. Please try again.";
    return input.map(normalizeErrorMessage).join("; ");
  }
  if (input && typeof input === "object") {
    const obj = input as Record<string, unknown>;
    if (typeof obj.detail === "string") return obj.detail;
    if (typeof obj.message === "string") return obj.message;
    try {
      const serialized = JSON.stringify(obj);
      return serialized === "{}" ? "Activation failed. Please try again." : serialized;
    } catch {
      return "Activation failed. Please try again.";
    }
  }
  return "Activation failed. Please try again.";
}

export function PolicySelectionForm() {
  const router = useRouter();
  const activationLock = useRef(false); // prevent duplicate submissions

  const [quotes, setQuotes] = useState<Record<string, PolicyQuote | null>>({
    basic: null, standard: null, pro: null,
  });
  const [loading, setLoading] = useState(true);
  const [errorMap, setErrorMap] = useState<Record<string, boolean>>({});
  const [selectedPlan, setSelectedPlan] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("selection");
  const [activationError, setActivationError] = useState("");
  const [hubId, setHubId] = useState("");

  // Auth + profile guard: onboarding page doesn't have RiderRouteGuard,
  // so each step component self-validates its prerequisites.
  useEffect(() => {
    let mounted = true;
    onboardingService.getRiderProfile().then(profileRes => {
      if (!mounted) return;
      if (profileRes.error || !profileRes.data?.hub_id) {
        router.replace("/onboarding/rider?step=profile");
        return;
      }
      // Payout token guard
      const fundToken = typeof window !== "undefined"
        ? localStorage.getItem("gs_fund_account_id")
        : null;
      if (!fundToken) {
        router.replace("/onboarding/rider?step=payout");
        return;
      }
      setHubId(profileRes.data.hub_id);
      fetchAllQuotes(profileRes.data.hub_id);
    });
    return () => { mounted = false; };
  }, [router]);

  const fetchAllQuotes = async (targetHubId: string) => {
    setLoading(true);
    setErrorMap({});

    const planKeys = ["basic", "standard", "pro"];
    const results = await Promise.allSettled(
      planKeys.map(plan =>
        onboardingService.getPolicyQuote(plan, targetHubId).then(res => {
          if (res.error) throw new Error("quote_failed");
          return { plan, data: res.data as PolicyQuote };
        })
      )
    );

    const updated: Record<string, PolicyQuote | null> = { basic: null, standard: null, pro: null };
    const errors: Record<string, boolean> = {};

    results.forEach((res, i) => {
      if (res.status === "fulfilled") {
        updated[res.value.plan] = res.value.data;
      } else {
        errors[planKeys[i]] = true;
      }
    });

    setQuotes(updated);
    setErrorMap(errors);
    setLoading(false);
    // Default to standard if available, else first successful
    if (updated.standard) setSelectedPlan("standard");
    else {
      const first = planKeys.find(p => updated[p] !== null);
      if (first) setSelectedPlan(first);
    }
  };

  const retryQuote = async (plan: string) => {
    if (!hubId) return;
    setErrorMap(prev => ({ ...prev, [plan]: false }));
    try {
      const res = await onboardingService.getPolicyQuote(plan, hubId);
      if (res.error) throw new Error();
      setQuotes(prev => ({ ...prev, [plan]: res.data as PolicyQuote }));
      if (!selectedPlan) setSelectedPlan(plan);
    } catch {
      setErrorMap(prev => ({ ...prev, [plan]: true }));
    }
  };

  const handleActivate = async () => {
    if (activationLock.current || !selectedPlan || !hubId) return;
    const fundAccountId = typeof window !== "undefined"
      ? localStorage.getItem("gs_fund_account_id")
      : null;
    if (!fundAccountId) {
      router.replace("/onboarding/rider?step=payout");
      return;
    }

    activationLock.current = true;
    setPhase("activating");
    setActivationError("");

    try {
      const res = await onboardingService.createPolicy({
        plan_name: selectedPlan,
        hub_id: hubId,
        razorpay_fund_account_id: fundAccountId,
      });

      if (res.error || !res.data) {
        const msg = normalizeErrorMessage(res.error?.message);
        // If rider already has active policy, treat onboarding as complete.
        if (msg.toLowerCase().includes("already has an active policy")) {
          setPhase("success");
          return;
        }

        // Fallback: API might return unhelpful payload, so verify active policy explicitly.
        const existingPolicy = await onboardingService.getPolicy();
        if (!existingPolicy.error && existingPolicy.data?.status === "active") {
          setPhase("success");
          return;
        }

        throw new Error(msg);
      }

      setPhase("success");
    } catch (err: any) {
      setActivationError(normalizeErrorMessage(err?.message));
      setPhase("error");
      activationLock.current = false; // release lock so user can retry
    }
  };

  const handleEnterDashboard = async () => {
    setPhase("activating"); // show spinner on "Enter Terminal" press
    if (typeof window !== "undefined") {
      localStorage.removeItem("gs_onboarding_required");
    }
    // Parallel hydration: confirm both profile and policy are readable
    await Promise.allSettled([
      onboardingService.getRiderProfile(),
      onboardingService.getPolicy(),
    ]);
    router.replace("/rider");
  };

  // ─── Success Screen ───────────────────────────────────────────────
  if (phase === "success" && selectedPlan) {
    const q = quotes[selectedPlan];
    return (
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
        className="flex-1 flex flex-col items-center justify-center text-center py-8"
      >
        {/* Pulsing shield */}
        <div className="relative w-24 h-24 mb-8">
          <div className="absolute inset-0 rounded-full bg-[var(--color-rider-primary)]/10 animate-ping" />
          <div className="relative w-full h-full rounded-full bg-[var(--color-rider-primary)]/10 border border-[var(--color-rider-primary)]/30 flex items-center justify-center">
            <span className="material-symbols-outlined text-[var(--color-rider-primary)] text-4xl" style={{ fontVariationSettings: "'FILL' 1" }}>
              shield
            </span>
          </div>
        </div>

        <h2 className="text-3xl font-['Space_Grotesk'] font-bold text-white mb-2">Shield Active</h2>
        <p className="text-white/50 text-sm font-['Manrope'] mb-8 max-w-[260px] leading-relaxed">
          Live weather monitoring and instant payout architecture are now enabled for your account.
        </p>

        {/* Policy summary card */}
        <div className="w-full bg-white/5 border border-white/10 rounded-2xl p-6 mb-8 text-left space-y-4">
          <div className="flex justify-between items-center pb-4 border-b border-white/5">
            <span className="text-white/50 text-xs font-['Manrope'] font-bold uppercase tracking-widest">Policy Tier</span>
            <span className="text-white font-['Space_Grotesk'] font-bold">{q?.plan_name}</span>
          </div>
          <div className="flex justify-between items-center pb-4 border-b border-white/5">
            <span className="text-white/50 text-xs font-['Manrope'] font-bold uppercase tracking-widest">Weekly Premium</span>
            <span className="text-[var(--color-rider-primary)] font-['Space_Grotesk'] font-bold">₹{q?.premium_amount}/wk</span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-white/50 text-xs font-['Manrope'] font-bold uppercase tracking-widest">Coverage</span>
            <span className="text-white font-['Space_Grotesk'] font-bold">{q?.coverage_percent}%</span>
          </div>
        </div>

        <motion.button
          onClick={handleEnterDashboard}
          whileTap={{ scale: 0.96 }}
          className="w-full py-4 rounded-full bg-[var(--color-rider-primary)] text-[#002635] font-['Space_Grotesk'] font-bold text-lg shadow-[0_0_20px_rgba(84,199,252,0.3)] flex items-center justify-center gap-2"
        >
          Enter Terminal
          <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>arrow_forward</span>
        </motion.button>
      </motion.div>
    );
  }

  // ─── Plan Cards ───────────────────────────────────────────────────
  const renderCard = (plan: string) => {
    const isError = errorMap[plan];
    const quote = quotes[plan];
    const isSelected = selectedPlan === plan;

    if (loading) {
      return (
        <div key={plan} className="w-full bg-white/5 border border-white/10 rounded-2xl p-6 animate-pulse space-y-4">
          <div className="flex justify-between">
            <div className="h-6 w-24 bg-white/10 rounded-md" />
            <div className="h-6 w-16 bg-white/10 rounded-md" />
          </div>
          <div className="h-4 w-full bg-white/10 rounded-md" />
          <div className="h-4 w-3/4 bg-white/10 rounded-md" />
        </div>
      );
    }

    if (isError) {
      return (
        <div key={plan} className="w-full bg-white/5 border border-[var(--color-rider-error)]/30 rounded-2xl p-6 flex flex-col items-center gap-3 text-center">
          <span className="material-symbols-outlined text-[var(--color-rider-error)]">portable_wifi_off</span>
          <p className="text-xs text-[var(--color-rider-error)] font-['Manrope']">
            {plan.charAt(0).toUpperCase() + plan.slice(1)} quote unavailable.
          </p>
          <button
            type="button"
            onClick={() => retryQuote(plan)}
            className="text-[10px] font-bold uppercase tracking-widest text-[var(--color-rider-error)] px-4 py-1.5 border border-[var(--color-rider-error)]/40 rounded-full hover:bg-[var(--color-rider-error)]/10 transition-colors"
          >
            Retry
          </button>
        </div>
      );
    }

    if (!quote) return null;

    return (
      <motion.button
        type="button"
        key={plan}
        whileTap={{ scale: 0.985 }}
        onClick={() => setSelectedPlan(plan)}
        className={`w-full text-left rounded-2xl p-6 border transition-all duration-250 relative overflow-hidden ${
          isSelected
            ? "bg-[#002635]/50 border-[var(--color-rider-primary)] shadow-[0_0_24px_rgba(84,199,252,0.15)]"
            : "bg-white/5 border-white/10 hover:border-white/20"
        }`}
      >
        {isSelected && (
          <div className="absolute top-4 right-4">
            <span className="material-symbols-outlined text-[var(--color-rider-primary)] text-xl" style={{ fontVariationSettings: "'FILL' 1" }}>
              check_circle
            </span>
          </div>
        )}

        <div className="flex justify-between items-start mb-4 pr-8">
          <div>
            <span className="block text-[10px] font-bold uppercase tracking-widest text-white/30 mb-1 font-['Manrope']">
              {plan} tier
            </span>
            <h3 className="text-2xl font-['Space_Grotesk'] font-extrabold text-white">{quote.plan_name}</h3>
          </div>
          <p className="text-2xl font-['Space_Grotesk'] font-bold text-[var(--color-rider-primary)]">
            ₹{quote.premium_amount}
            <span className="text-sm font-medium text-white/40">/wk</span>
          </p>
        </div>

        <div className="space-y-2 mb-5">
          <div className="flex justify-between text-sm">
            <span className="text-white/50 font-['Manrope']">Coverage</span>
            <span className="font-bold text-white">{quote.coverage_percent}%</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-white/50 font-['Manrope']">Weekly cap</span>
            <span className="font-bold text-white">₹{quote.weekly_cap.toLocaleString("en-IN")}</span>
          </div>
        </div>

        <div className="pt-4 border-t border-white/5 space-y-3">
          <div className="flex gap-2 flex-wrap">
            {quote.covered_triggers.map((t, i) => (
              <span key={i} className="text-[10px] font-bold uppercase tracking-wide bg-[var(--color-rider-primary)]/10 text-[var(--color-rider-primary)] px-2 py-1 rounded border border-[var(--color-rider-primary)]/20">
                {t}
              </span>
            ))}
          </div>
          <p className="text-xs text-white/35 font-['Manrope'] leading-relaxed">{quote.quote_explanation}</p>
        </div>
      </motion.button>
    );
  };

  return (
    <div className="flex-1 flex flex-col relative">
      {/* Activation error banner */}
      <AnimatePresence>
        {phase === "error" && activationError && (
          <motion.div
            initial={{ opacity: 0, height: 0, marginBottom: 0 }}
            animate={{ opacity: 1, height: "auto", marginBottom: 16 }}
            exit={{ opacity: 0, height: 0, marginBottom: 0 }}
            className="bg-[var(--color-rider-error)]/20 border border-[var(--color-rider-error)] text-[var(--color-rider-error)] text-xs font-['Manrope'] px-4 py-3 rounded-xl flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-sm">error</span>
            {activationError}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="space-y-4 pb-36">
        {renderCard("basic")}
        {renderCard("standard")}
        {renderCard("pro")}
      </div>

      {/* Sticky CTA */}
      <div className="fixed bottom-0 left-0 right-0 px-6 pb-8 pt-4 max-w-md mx-auto bg-gradient-to-t from-[var(--color-rider-bg)] via-[var(--color-rider-bg)]/90 to-transparent z-10">
        <motion.button
          onClick={handleActivate}
          whileTap={{ scale: 0.96 }}
          className="w-full py-4 rounded-full bg-[var(--color-rider-primary)] text-[#002635] font-['Space_Grotesk'] font-bold text-lg shadow-[0_0_20px_rgba(84,199,252,0.3)] disabled:opacity-40 flex items-center justify-center gap-2 transition-opacity"
          disabled={phase === "activating" || !selectedPlan || loading}
        >
          {phase === "activating" ? (
            <span className="material-symbols-outlined animate-spin">autorenew</span>
          ) : (
            <>
              Activate Shield
              <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>shield</span>
            </>
          )}
        </motion.button>
      </div>
    </div>
  );
}
