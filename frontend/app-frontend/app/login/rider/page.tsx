"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { RiderPageTransition } from "@/lib/motion/safeWrappers";
import Link from "next/link";
import { authService } from "@/lib/api/auth";

export default function RiderLogin() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("Invalid email or password");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setErrorMessage("Please enter your email and password.");
      setStatus("error");
      return;
    }
    setStatus("loading");

    try {
      const res = mode === "login"
        ? await authService.loginRider(email, password)
        : await authService.registerRider(email, password);

      if (res.error || !res.data) {
        setErrorMessage(res.error?.message || "Authentication failed");
        setStatus("error");
        return;
      }

      // Keep registration deterministic: start onboarding at profile step.
      if (mode === "register") {
        router.push("/onboarding/rider?step=profile");
      } else {
        router.push("/rider");
      }
    } catch {
      setErrorMessage("Something went wrong. Please try again.");
      setStatus("error");
    }
  };

  const clearError = () => { if (status === "error") setStatus("idle"); };

  return (
    <RiderPageTransition>
      <main className="min-h-screen bg-[var(--color-rider-bg)] text-white flex flex-col pt-safe-top px-6 pb-8">
        <Link href="/login" className="flex items-center text-white/50 hover:text-white transition-colors w-max mt-12 mb-12">
          <span className="material-symbols-outlined mr-2">arrow_back</span>
          <span className="font-['Manrope'] text-sm font-medium">Back</span>
        </Link>

        <div className="w-full max-w-sm mx-auto flex-1 flex flex-col">
          <div className="mb-10 text-center">
            <div className="w-16 h-16 rounded-full bg-[var(--color-rider-primary)]/10 border border-[var(--color-rider-primary)]/20 flex items-center justify-center mx-auto mb-6">
              <span className="material-symbols-outlined text-3xl text-[var(--color-rider-primary)]">motorcycle</span>
            </div>
            <h1 className="text-3xl font-['Space_Grotesk'] font-bold tracking-tight mb-2">
              {mode === "login" ? "Welcome Back" : "Join GigShield"}
            </h1>
            <p className="text-white/40 text-sm font-['Manrope']">
              {mode === "login" ? "Sign in to your rider account" : "Create a new rider account"}
            </p>
          </div>

          {/* Login / Register Toggle */}
          <div className="flex bg-white/5 p-1 rounded-xl border border-white/10 mb-6">
            <button
              type="button"
              onClick={() => { setMode("login"); clearError(); }}
              className={`flex-1 py-2.5 text-sm font-['Space_Grotesk'] font-bold rounded-lg transition-all ${mode === "login" ? "bg-[var(--color-rider-primary)] text-[#002635]" : "text-white/60 hover:text-white"}`}
            >
              Sign In
            </button>
            <button
              type="button"
              onClick={() => { setMode("register"); clearError(); }}
              className={`flex-1 py-2.5 text-sm font-['Space_Grotesk'] font-bold rounded-lg transition-all ${mode === "register" ? "bg-[var(--color-rider-primary)] text-[#002635]" : "text-white/60 hover:text-white"}`}
            >
              Register
            </button>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6" noValidate>
            <AnimatePresence>
              {status === "error" && (
                <motion.div
                  initial={{ opacity: 0, height: 0, y: -10, marginBottom: 0 }}
                  animate={{ opacity: 1, height: "auto", y: 0, marginBottom: 0 }}
                  exit={{ opacity: 0, height: 0, scale: 0.95, marginBottom: 0 }}
                  className="bg-[var(--color-rider-error)]/20 border border-[var(--color-rider-error)] text-[var(--color-rider-error)] text-xs font-['Manrope'] font-medium px-4 py-3 rounded-xl flex items-center gap-2"
                >
                  <span className="material-symbols-outlined text-sm">error</span>
                  {errorMessage}
                </motion.div>
              )}
            </AnimatePresence>

            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-xs font-['Manrope'] font-bold text-white/70 uppercase tracking-widest pl-1">Email Address</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => { setEmail(e.target.value); clearError(); }}
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all"
                  placeholder="you@example.com"
                  autoComplete="email"
                  inputMode="email"
                />
              </div>

              <div className="space-y-2">
                <label className="text-xs font-['Manrope'] font-bold text-white/70 uppercase tracking-widest pl-1">Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); clearError(); }}
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-4 text-white font-['Manrope'] focus:outline-none focus:border-[var(--color-rider-primary)] focus:ring-1 focus:ring-[var(--color-rider-primary)] transition-all"
                  placeholder="••••••••"
                  autoComplete={mode === "register" ? "new-password" : "current-password"}
                />
              </div>
            </div>

            <motion.button
              whileTap={{ scale: 0.96 }}
              className="w-full py-4 rounded-full bg-[var(--color-rider-primary)] text-[#002635] font-['Space_Grotesk'] font-bold text-lg shadow-[0_0_20px_rgba(84,199,252,0.3)] disabled:opacity-50"
              disabled={status === "loading"}
            >
              {status === "loading" ? (
                <span className="material-symbols-outlined animate-spin inline-block">autorenew</span>
              ) : (
                mode === "login" ? "Sign In" : "Create Account"
              )}
            </motion.button>
          </form>

          <p className="text-center text-xs text-white/30 font-['Manrope'] mt-6">
            {mode === "login" ? "New to GigShield?" : "Already have an account?"}{" "}
            <button
              type="button"
              onClick={() => { setMode(mode === "login" ? "register" : "login"); clearError(); }}
              className="text-[var(--color-rider-primary)] font-bold hover:underline"
            >
              {mode === "login" ? "Create an account" : "Sign in instead"}
            </button>
          </p>
        </div>
      </main>
    </RiderPageTransition>
  );
}
