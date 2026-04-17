"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence, Variants } from "framer-motion";
import { AdminInstantLoad } from "@/lib/motion/safeWrappers";
import Link from "next/link";
import { authService } from "@/lib/api/auth";

export default function AdminLogin() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("Invalid credentials provided.");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      setErrorMessage("Invalid credentials provided.");
      setStatus("error");
      return;
    }

    setStatus("loading");
    const res = await authService.loginAdmin(username, password);

    if (res.error || !res.data) {
      setErrorMessage(res.error?.message || "Invalid credentials provided.");
      setStatus("error");
      return;
    }

    setTimeout(() => {
      setStatus("idle");
      router.push("/admin");
    }, 400); // Admin flows emulate raw computation speed
  };

  return (
    <AdminInstantLoad>
      <main className="min-h-screen bg-[var(--color-admin-bg)] text-[var(--color-admin-text)] flex items-center justify-center font-['Inter']">
        <div className="absolute top-4 left-4">
          <Link href="/login" className="flex items-center text-[var(--color-admin-outline)] hover:text-white transition-colors text-xs font-['JetBrains_Mono'] uppercase tracking-widest">
            <span className="material-symbols-outlined text-sm mr-1">arrow_back</span>
            Abort_Sequence
          </Link>
        </div>

        <div className="w-full max-w-md bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 p-8 shadow-[0_24px_48px_-12px_rgba(6,14,32,0.8)]">
          <div className="border-b border-[var(--color-admin-outline)]/20 pb-4 mb-8 flex items-center gap-4">
            <span className="material-symbols-outlined text-[var(--color-admin-primary)]">terminal</span>
            <h1 className="text-xl font-bold uppercase tracking-widest text-[var(--color-admin-primary)]">The Core</h1>
            <span className="ml-auto text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-outline)] animate-pulse">_STANDBY</span>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            <AnimatePresence>
              {status === "error" && (
                <motion.div 
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="bg-[#93000a]/20 border-l-2 border-[var(--color-admin-error)] text-[var(--color-admin-error)] p-3 text-[10px] font-['JetBrains_Mono'] uppercase"
                >
                  <span className="mr-2">ERR_AUTH_FAIL:</span> {errorMessage}
                </motion.div>
              )}
            </AnimatePresence>

            <div className="space-y-4">
              <div className="space-y-1">
                <label className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-outline)] uppercase tracking-wider block">Username</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-admin-tertiary)] font-['JetBrains_Mono'] text-sm">&gt;</span>
                  <input 
                    type="text"
                    value={username}
                    onChange={(e) => { setUsername(e.target.value); setStatus("idle"); }}
                    className="w-full bg-[var(--color-admin-surface-high)] border border-[var(--color-admin-outline)]/20 rounded-sm pl-8 pr-4 py-3 text-white font-['JetBrains_Mono'] text-sm focus:outline-none focus:border-[var(--color-admin-primary)]/50 transition-colors placeholder:text-[var(--color-admin-outline)]/40"
                    placeholder="sysadmin"
                    autoComplete="off"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-outline)] uppercase tracking-wider block">Secret Key</label>
                <div className="relative">
                  <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-admin-tertiary)] font-['JetBrains_Mono'] text-sm">&gt;</span>
                  <input 
                    type="password"
                    value={password}
                    onChange={(e) => { setPassword(e.target.value); setStatus("idle"); }}
                    className="w-full bg-[var(--color-admin-surface-high)] border border-[var(--color-admin-outline)]/20 rounded-sm pl-8 pr-4 py-3 text-white font-['JetBrains_Mono'] text-sm focus:outline-none focus:border-[var(--color-admin-primary)]/50 transition-colors placeholder:text-[var(--color-admin-outline)]/40"
                    placeholder="••••••••"
                    autoComplete="off"
                  />
                </div>
              </div>
            </div>

            <button 
              className="w-full py-3 bg-transparent border border-[var(--color-admin-outline)]/40 hover:bg-[var(--color-admin-primary)]/10 hover:border-[var(--color-admin-primary)] text-white text-[10px] font-['JetBrains_Mono'] font-bold uppercase tracking-[0.2em] transition-all flex items-center justify-center gap-2 rounded-sm"
              disabled={status === "loading"}
            >
              {status === "loading" ? (
                <>EXECUTING <span className="w-1.5 h-1.5 bg-white rounded-full animate-pulse"></span></>
              ) : (
                <>INIT_SESSION</>
              )}
            </button>
          </form>
        </div>
      </main>
    </AdminInstantLoad>
  );
}
