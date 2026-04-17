"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { onboardingService } from "@/lib/api/onboarding";
import { motion, AnimatePresence } from "framer-motion";

const CITIES = ["Bangalore", "Mumbai", "Delhi", "Chennai", "Hyderabad"];
const PLATFORMS = ["Zepto", "Blinkit", "Instamart"];

export function ProfileForm() {
  const router = useRouter();
  const submitLock = useRef(false);

  const [formData, setFormData] = useState({
    name: "",
    phone: "",
    platform: "",
    city: "",
    declared_income: "",
    hub_id: "",
  });

  const [hubsList, setHubsList] = useState<{ id: string; name: string }[]>([]);
  const [isLoadingHubs, setIsLoadingHubs] = useState(false);
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  // Hydrate from sessionStorage on mount (back-navigation resume)
  useEffect(() => {
    let mounted = true;
    onboardingService.getRiderProfile().then(res => {
      if (!mounted || !res.data) return;
      const d = res.data;
      setFormData({
        name: d.name ?? "",
        phone: d.phone ?? "",
        platform: d.platform ?? "",
        city: d.city ?? "",
        declared_income: d.declared_income != null ? String(d.declared_income) : "",
        hub_id: d.hub_id ?? "",
      });
    });
    return () => { mounted = false; };
  }, []);

  // Fetch hubs whenever city changes; also clear stale hub_id
  const prevCity = useRef("");
  useEffect(() => {
    if (!formData.city) {
      setHubsList([]);
      return;
    }

    // Only clear hub_id when city genuinely changes (not during initial hydration)
    if (prevCity.current && prevCity.current !== formData.city) {
      setFormData(prev => ({ ...prev, hub_id: "" }));
    }
    prevCity.current = formData.city;

    let mounted = true;
    setIsLoadingHubs(true);
    onboardingService.searchHubs(formData.city).then(res => {
      if (!mounted) return;
      setHubsList(res.data ?? []);
      setIsLoadingHubs(false);
    });
    return () => { mounted = false; };
  }, [formData.city]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    if (status === "error") setStatus("idle");
  };

  const isValid =
    formData.name.trim().length > 1 &&
    formData.phone.trim().length >= 10 &&
    formData.platform !== "" &&
    formData.city !== "" &&
    formData.hub_id !== "" &&
    formData.declared_income !== "" &&
    parseFloat(formData.declared_income) >= 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitLock.current || !isValid) return;

    // Extra phone validation
    const phoneDigits = formData.phone.replace(/\D/g, "");
    if (phoneDigits.length < 10) {
      setErrorMessage("Enter a valid 10-digit phone number.");
      setStatus("error");
      return;
    }

    submitLock.current = true;
    setStatus("loading");

    const payload = {
      name: formData.name.trim(),
      phone: phoneDigits,
      platform: formData.platform,
      city: formData.city,
      declared_income: parseFloat(formData.declared_income),
      hub_id: formData.hub_id,
    };

    try {
      const res = await onboardingService.createRiderProfile(payload);
      if (res.error || !res.data) throw new Error(res.error?.message ?? "Profile creation failed");
      router.replace("/onboarding/rider?step=payout");
    } catch (err: any) {
      setErrorMessage(err.message ?? "Failed to save profile. Please try again.");
      setStatus("error");
      submitLock.current = false;
    }
  };

  const isIncomeHigh = parseFloat(formData.declared_income) > 2000;

  return (
    <form onSubmit={handleSubmit} className="flex-1 flex flex-col" noValidate>
      {/* Error Banner */}
      <AnimatePresence>
        {status === "error" && (
          <motion.div
            initial={{ opacity: 0, height: 0, marginBottom: 0 }}
            animate={{ opacity: 1, height: "auto", marginBottom: 20 }}
            exit={{ opacity: 0, height: 0, marginBottom: 0 }}
            transition={{ duration: 0.2 }}
            className="bg-[var(--color-rider-error)]/20 border border-[var(--color-rider-error)] text-[var(--color-rider-error)] text-xs font-['Manrope'] font-medium px-4 py-3 rounded-xl flex items-center gap-2"
          >
            <span className="material-symbols-outlined text-sm">error</span>
            {errorMessage}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="space-y-5 pb-36">
        {/* Full Name */}
        <div className="space-y-2">
          <label className="text-xs font-['Manrope'] font-bold text-white/60 uppercase tracking-widest pl-1">
            Full Name
          </label>
          <input
            type="text"
            name="name"
            value={formData.name}
            onChange={handleChange}
            autoComplete="name"
            className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all"
            placeholder="Your full name"
          />
        </div>

        {/* Phone */}
        <div className="space-y-2">
          <label className="text-xs font-['Manrope'] font-bold text-white/60 uppercase tracking-widest pl-1">
            Phone Number
          </label>
          <input
            type="tel"
            name="phone"
            value={formData.phone}
            onChange={handleChange}
            autoComplete="tel"
            inputMode="tel"
            className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all"
            placeholder="+91 98765 43210"
          />
        </div>

        {/* Platform */}
        <div className="space-y-2">
          <label className="text-xs font-['Manrope'] font-bold text-white/60 uppercase tracking-widest pl-1">
            Gig Platform
          </label>
          <select
            name="platform"
            value={formData.platform}
            onChange={handleChange}
            className="w-full bg-[#0a0e14] border border-white/10 rounded-xl px-4 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all appearance-none"
          >
            <option value="">Select platform</option>
            {PLATFORMS.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>

        {/* City + Hub — 2 column grid */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <label className="text-xs font-['Manrope'] font-bold text-white/60 uppercase tracking-widest pl-1">
              City
            </label>
            <select
              name="city"
              value={formData.city}
              onChange={handleChange}
              className="w-full bg-[#0a0e14] border border-white/10 rounded-xl px-3 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all appearance-none"
            >
              <option value="">Select city</option>
              {CITIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          <div className="space-y-2 relative">
            <label className="text-xs font-['Manrope'] font-bold text-white/60 uppercase tracking-widest pl-1 flex items-center gap-1">
              Hub Node
              {isLoadingHubs && (
                <span className="material-symbols-outlined animate-spin text-[10px] text-[var(--color-rider-primary)]">
                  autorenew
                </span>
              )}
            </label>
            <select
              name="hub_id"
              value={formData.hub_id}
              onChange={handleChange}
              disabled={!formData.city || isLoadingHubs || hubsList.length === 0}
              className="w-full bg-[#0a0e14] border border-white/10 rounded-xl px-3 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all appearance-none disabled:opacity-30"
            >
              <option value="">
                {!formData.city ? "City first" : isLoadingHubs ? "Loading…" : "Select hub"}
              </option>
              {hubsList.map(h => (
                <option key={h.id} value={h.id}>{h.name}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Declared Income */}
        <div className="space-y-2">
          <label className="text-xs font-['Manrope'] font-bold text-white/60 uppercase tracking-widest pl-1">
            Daily Income (₹)
          </label>
          <input
            type="number"
            name="declared_income"
            value={formData.declared_income}
            onChange={handleChange}
            inputMode="numeric"
            min="0"
            className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all"
            placeholder="e.g. 1200"
          />
          <AnimatePresence>
            {isIncomeHigh && (
              <motion.p
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2 }}
                className="text-[10px] text-[var(--color-rider-primary)] pl-2 font-['Manrope'] overflow-hidden"
              >
                Income above ₹2,000/day may require additional underwriting verification.
              </motion.p>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Sticky CTA */}
      <div className="fixed bottom-0 left-0 right-0 px-6 pb-8 pt-4 max-w-md mx-auto bg-gradient-to-t from-[var(--color-rider-bg)] via-[var(--color-rider-bg)]/90 to-transparent z-10">
        <motion.button
          whileTap={{ scale: 0.96 }}
          className="w-full py-4 rounded-full bg-[var(--color-rider-primary)] text-[#002635] font-['Space_Grotesk'] font-bold text-lg shadow-[0_0_20px_rgba(84,199,252,0.3)] disabled:opacity-40 transition-opacity flex items-center justify-center gap-2"
          disabled={status === "loading" || !isValid}
        >
          {status === "loading" ? (
            <span className="material-symbols-outlined animate-spin">autorenew</span>
          ) : (
            <>
              Continue Setup
              <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>arrow_forward</span>
            </>
          )}
        </motion.button>
      </div>
    </form>
  );
}
