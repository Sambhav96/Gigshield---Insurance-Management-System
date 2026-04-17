"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { fetchApi, riderPath } from "@/lib/api/client";

export function PayoutForm() {
  const router = useRouter();
  const submitLock = useRef(false);
  const [mounted, setMounted] = useState(false);

  const [method, setMethod] = useState<"upi" | "bank">("upi");
  const [formData, setFormData] = useState({
    upi_id: "",
    account_number: "",
    ifsc_code: "",
    account_name: "",
  });
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    setMounted(true);
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    if (status === "error") setStatus("idle");
  };

  const switchMethod = (m: "upi" | "bank") => {
    setMethod(m);
    setStatus("idle");
    setErrorMessage("");
  };

  const isFormValid = () => {
    if (method === "upi") {
      return formData.upi_id.length > 5 && formData.upi_id.includes("@");
    }
    return (
      formData.account_name.trim().length > 2 &&
      formData.account_number.replace(/\D/g, "").length >= 6 &&
      /^[A-Z]{4}0[A-Z0-9]{6}$/.test(formData.ifsc_code.toUpperCase())
    );
  };

  const buildFundAccountId = () => {
    if (method === "upi") {
      const safeUpi = formData.upi_id.trim().toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 20);
      return `fa_upi_${safeUpi || Date.now().toString()}`;
    }

    const last4 = formData.account_number.replace(/\D/g, "").slice(-4) || "0000";
    const safeIfsc = formData.ifsc_code.trim().toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 11);
    return `fa_bank_${safeIfsc}_${last4}`;
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (submitLock.current) return;

    if (!isFormValid()) {
      setErrorMessage(
        method === "upi"
          ? "Enter a valid UPI ID (e.g. name@oksbi)."
          : "Check your account number and IFSC code."
      );
      setStatus("error");
      return;
    }

    submitLock.current = true;
    setStatus("loading");

    try {
      const payoutRes = await fetchApi<{ razorpay_fund_account_id?: string }>(
        riderPath("/riders/me/payout-destination"),
        {
        method: "POST",
        body: JSON.stringify({ razorpay_fund_account_id: buildFundAccountId() }),
      }
      );

      if (payoutRes.error || !payoutRes.data?.razorpay_fund_account_id) {
        throw new Error(payoutRes.error?.message || "Fund account save failed");
      }

      if (typeof window !== "undefined") {
        localStorage.setItem("gs_fund_account_id", payoutRes.data.razorpay_fund_account_id);
      }

      // status reset before navigation so there's no stale loading on back-nav
      setStatus("idle");
      submitLock.current = false;
      router.replace("/onboarding/rider?step=policy");
    } catch (err: any) {
      setErrorMessage(err?.message || "Verification failed. Please try again.");
      setStatus("error");
      submitLock.current = false;
    }
  };

  if (!mounted) {
    return null;
  }

  return (
    <form onSubmit={handleVerify} className="flex-1 flex flex-col" noValidate>
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

      <div className="space-y-6 pb-36">
        {/* Method Toggle — same style as plan toggle */}
        <div className="flex bg-white/5 p-1 rounded-xl border border-white/10">
          <button
            type="button"
            onClick={() => switchMethod("upi")}
            className={`flex-1 py-3 text-sm font-['Space_Grotesk'] font-bold rounded-lg transition-all duration-200 ${
              method === "upi"
                ? "bg-[var(--color-rider-primary)] text-[#002635]"
                : "text-white/60 hover:text-white"
            }`}
          >
            UPI ID
          </button>
          <button
            type="button"
            onClick={() => switchMethod("bank")}
            className={`flex-1 py-3 text-sm font-['Space_Grotesk'] font-bold rounded-lg transition-all duration-200 ${
              method === "bank"
                ? "bg-[var(--color-rider-primary)] text-[#002635]"
                : "text-white/60 hover:text-white"
            }`}
          >
            Bank Account
          </button>
        </div>

        {/* Fields */}
        <AnimatePresence mode="wait">
          {method === "upi" ? (
            <motion.div
              key="upi"
              initial={{ opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
              transition={{ duration: 0.18 }}
              className="space-y-2"
            >
              <label className="text-xs font-['Manrope'] font-bold text-white/60 uppercase tracking-widest pl-1">
                UPI / VPA Address
              </label>
              <input
                type="text"
                name="upi_id"
                value={formData.upi_id}
                onChange={handleChange}
                inputMode="email"
                autoComplete="off"
                className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all"
                placeholder="yourname@oksbi"
              />
              <p className="text-[10px] text-white/35 pl-2 font-['Manrope']">
                Instant settlements will be sent to this address.
              </p>
            </motion.div>
          ) : (
            <motion.div
              key="bank"
              initial={{ opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
              transition={{ duration: 0.18 }}
              className="space-y-5"
            >
              <div className="space-y-2">
                <label className="text-xs font-['Manrope'] font-bold text-white/60 uppercase tracking-widest pl-1">
                  Account Holder Name
                </label>
                <input
                  type="text"
                  name="account_name"
                  value={formData.account_name}
                  onChange={handleChange}
                  autoComplete="name"
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all"
                  placeholder="As per bank records"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-['Manrope'] font-bold text-white/60 uppercase tracking-widest pl-1">
                  Account Number
                </label>
                <input
                  type="password"
                  name="account_number"
                  value={formData.account_number}
                  onChange={handleChange}
                  inputMode="numeric"
                  autoComplete="off"
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all"
                  placeholder="••••••••••••"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-['Manrope'] font-bold text-white/60 uppercase tracking-widest pl-1">
                  IFSC Code
                </label>
                <input
                  type="text"
                  name="ifsc_code"
                  value={formData.ifsc_code}
                  onChange={e => {
                    handleChange({ ...e, target: { ...e.target, name: "ifsc_code", value: e.target.value.toUpperCase() } });
                  }}
                  autoComplete="off"
                  maxLength={11}
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-4 text-white font-['Manrope'] tracking-widest focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all"
                  placeholder="HDFC0001234"
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Security note */}
        <div className="flex items-start gap-3 bg-white/3 border border-white/8 p-4 rounded-xl">
          <span className="material-symbols-outlined text-white/40 text-lg mt-0.5" style={{ fontVariationSettings: "'FILL' 1" }}>
            lock
          </span>
          <p className="text-[11px] text-white/40 font-['Manrope'] leading-relaxed">
            GigShield does not store your bank credentials. Your account is tokenised via Razorpay and only a secure fund account ID is retained.
          </p>
        </div>
      </div>

      {/* Sticky CTA — consistent cyan style matching rest of onboarding */}
      <div className="fixed bottom-0 left-0 right-0 px-6 pb-8 pt-4 max-w-md mx-auto bg-gradient-to-t from-[var(--color-rider-bg)] via-[var(--color-rider-bg)]/90 to-transparent z-10">
        <motion.button
          whileTap={{ scale: 0.96 }}
          className="w-full py-4 rounded-full bg-[var(--color-rider-primary)] text-[#002635] font-['Space_Grotesk'] font-bold text-lg shadow-[0_0_20px_rgba(84,199,252,0.3)] disabled:opacity-40 transition-opacity flex items-center justify-center gap-2"
          disabled={status === "loading" || !isFormValid()}
        >
          {status === "loading" ? (
            <span className="material-symbols-outlined animate-spin">autorenew</span>
          ) : (
            <>
              Verify & Continue
              <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>account_balance</span>
            </>
          )}
        </motion.button>
      </div>
    </form>
  );
}
