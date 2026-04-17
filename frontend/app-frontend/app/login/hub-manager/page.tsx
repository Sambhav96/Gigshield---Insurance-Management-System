"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence, Variants } from "framer-motion";
import { HubPageCrossfade } from "@/lib/motion/safeWrappers";
import Link from "next/link";
import { authService } from "@/lib/api/auth";

export default function HubLogin() {
  const router = useRouter();
  const [hubId, setHubId] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("IDENT/AUTH rejection. Invalid credentials.");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hubId || !password) {
      setErrorMessage("IDENT/AUTH rejection. Invalid credentials.");
      setStatus("error");
      return;
    }

    setStatus("loading");
    const res = await authService.loginHub(hubId, password);

    if (res.error || !res.data) {
      setErrorMessage(res.error?.message || "IDENT/AUTH rejection. Invalid credentials.");
      setStatus("error");
      return;
    }

    setTimeout(() => {
      setStatus("idle");
      router.push("/hub");
    }, 800);
  };

  return (
    <HubPageCrossfade>
      <main className="min-h-screen bg-[var(--color-hub-bg)] text-[var(--color-hub-text)] flex relative overflow-hidden">
        <div className="hub-grain absolute inset-0 z-0"></div>
        {/* Soft green ambient light */}
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-[var(--color-hub-secondary)]/10 blur-[100px] rounded-full pointer-events-none z-0"></div>

        <div className="w-full sm:w-[480px] m-auto z-10 flex flex-col">
          <Link href="/login" className="flex items-center text-white/40 hover:text-white transition-opacity mb-8 w-max">
            <span className="material-symbols-outlined mr-2">arrow_back</span>
            <span className="font-['DM_Sans'] text-sm">Return</span>
          </Link>
          
          <div className="bg-[var(--color-hub-surface-low)] border border-[var(--color-hub-secondary)]/5 rounded-2xl p-8 sm:p-12 shadow-[0_0_40px_rgba(74,222,128,0.03)]">
            <div className="mb-10">
              <h1 className="text-3xl font-['Syne'] font-black tracking-tighter text-white mb-2">Hub Sentinel</h1>
              <p className="font-['DM_Sans'] text-white/50 text-sm">Access operational zone matrix.</p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-6">
              <AnimatePresence mode="wait">
                {status === "error" && (
                  <motion.div 
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="p-3 bg-[var(--color-hub-error)]/10 text-[var(--color-hub-error)] text-xs font-['DM_Sans'] rounded-lg"
                  >
                    {errorMessage}
                  </motion.div>
                )}
              </AnimatePresence>

              <div className="space-y-4">
                <div className="space-y-2">
                  <label className="text-[10px] font-['JetBrains_Mono'] text-white/40 uppercase tracking-widest pl-1">Ident Key</label>
                  {/* No-line rule applied. Soft inset background instead of explicit borders */}
                  <input 
                    type="text"
                    value={hubId}
                    onChange={(e) => { setHubId(e.target.value); setStatus("idle"); }}
                    className="w-full bg-[var(--color-hub-surface-high)] rounded-xl px-4 py-3.5 text-white font-['JetBrains_Mono'] focus:outline-none focus:bg-[#32343e] transition-colors"
                    placeholder="HUB-00-XXXX"
                  />
                </div>
                
                <div className="space-y-2">
                  <label className="text-[10px] font-['JetBrains_Mono'] text-white/40 uppercase tracking-widest pl-1">Passcode</label>
                  <input 
                    type="password"
                    value={password}
                    onChange={(e) => { setPassword(e.target.value); setStatus("idle"); }}
                    className="w-full bg-[var(--color-hub-surface-high)] rounded-xl px-4 py-3.5 text-white font-['JetBrains_Mono'] focus:outline-none focus:bg-[#32343e] transition-colors"
                    placeholder="••••••••"
                  />
                </div>
              </div>

              <button 
                className="w-full py-4 mt-4 rounded-xl bg-[var(--color-hub-secondary)] text-[#00210c] font-['DM_Sans'] font-bold shadow-[0_0_24px_rgba(74,222,128,0.2)] disabled:opacity-50 transition-transform active:scale-[0.98] flex items-center justify-center gap-2"
                disabled={status === "loading"}
              >
                {status === "loading" ? (
                  <>Verifying Matrix <span className="material-symbols-outlined animate-spin text-sm">autorenew</span></>
                ) : (
                  <>Initiate Link <span className="material-symbols-outlined text-sm">login</span></>
                )}
              </button>
            </form>
          </div>
        </div>
      </main>
    </HubPageCrossfade>
  );
}
