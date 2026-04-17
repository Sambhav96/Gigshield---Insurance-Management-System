"use client";

import { motion, Variants } from "framer-motion";
import Link from "next/link";

export default function LandingPage() {
  const containerVariants: Variants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: { staggerChildren: 0.15, delayChildren: 0.1 },
    },
  };

  const itemVariants: Variants = {
    hidden: { opacity: 0, y: 15 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.6, ease: "easeOut" } },
  };

  return (
    <main className="min-h-screen bg-black text-white selection:bg-white/20 flex flex-col items-center justify-start overflow-x-hidden relative font-['Inter']">
      {/* Background ambient glow - Neutral White/Gray so it doesn't favor one portal */}
      <div className="absolute top-0 left-1/2 -translate-x-1/2 w-full max-w-4xl h-[500px] bg-white/5 blur-[120px] rounded-full pointer-events-none" />

      <motion.div 
        className="w-full max-w-5xl mx-auto px-6 py-24 md:py-32 flex flex-col items-center z-10"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
      >
        {/* Hero Copy */}
        <motion.div variants={itemVariants} className="text-center max-w-3xl mb-24 space-y-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 bg-white/5 border border-white/10 rounded-full mb-4 shadow-xl">
            <span className="w-2 h-2 rounded-full bg-white animate-pulse" />
            <span className="text-[10px] font-['JetBrains_Mono'] tracking-widest uppercase text-white/70">Unified Platform Node</span>
          </div>
          <h1 className="text-5xl md:text-7xl font-['Syne'] font-black tracking-tighter text-white">
            GigShield
          </h1>
          <p className="text-lg md:text-xl font-['DM_Sans'] text-white/60 leading-relaxed max-w-2xl mx-auto">
            The precision sentinel for the gig economy. Empowering riders, equipping hubs, and informing administration through real-time telemetry and actuarial clarity.
          </p>
        </motion.div>

        {/* Portal Entry Nodes */}
        <motion.div variants={containerVariants} className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full">
          
          {/* Rider Card */}
          <Link href="/login/rider" className="block focus:outline-none">
            <motion.div 
              variants={itemVariants}
              whileHover={{ y: -6, transition: { duration: 0.2, ease: "easeOut" } }}
              whileTap={{ scale: 0.98 }}
              className="h-full flex flex-col bg-[var(--color-rider-bg)] border border-white/5 rounded-2xl p-8 relative overflow-hidden group transition-colors hover:border-[var(--color-rider-primary)]/30"
            >
              <div className="absolute inset-0 bg-gradient-to-b from-[var(--color-rider-primary)]/0 via-transparent to-[var(--color-rider-primary)]/5 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
              <div className="w-12 h-12 rounded-xl bg-[var(--color-rider-primary)]/10 flex items-center justify-center mb-6">
                <span className="material-symbols-outlined text-[var(--color-rider-primary)]" style={{ fontVariationSettings: "'FILL' 1" }}>two_wheeler</span>
              </div>
              <h2 className="text-2xl font-['Space_Grotesk'] font-bold text-white mb-3 tracking-tight">Rider Portal</h2>
              <p className="text-sm font-['Manrope'] text-white/50 flex-1 leading-relaxed">
                Mobile-first telemetry, earnings protection, and intelligent risk oracles for active shifts.
              </p>
              <div className="mt-8 flex items-center text-[var(--color-rider-primary)] text-xs font-bold uppercase tracking-widest group-hover:translate-x-2 transition-transform duration-300">
                Access Portal <span className="material-symbols-outlined text-sm ml-1">arrow_forward</span>
              </div>
            </motion.div>
          </Link>

          {/* Hub Card */}
          <Link href="/login/hub-manager" className="block focus:outline-none">
            <motion.div 
              variants={itemVariants}
              whileHover={{ y: -6, transition: { duration: 0.2, ease: "easeOut" } }}
              whileTap={{ scale: 0.98 }}
              className="h-full flex flex-col bg-[var(--color-hub-surface)] border border-white/5 rounded-2xl p-8 relative overflow-hidden group transition-colors hover:border-[var(--color-hub-secondary)]/30"
            >
              <div className="absolute inset-0 bg-gradient-to-b from-[var(--color-hub-secondary)]/0 via-transparent to-[var(--color-hub-secondary)]/5 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
              <div className="w-12 h-12 rounded-xl bg-[var(--color-hub-secondary)]/10 flex items-center justify-center mb-6">
                <span className="material-symbols-outlined text-[var(--color-hub-secondary)]" style={{ fontVariationSettings: "'FILL' 1" }}>hub</span>
              </div>
              <h2 className="text-2xl font-['Syne'] font-bold text-white mb-3 tracking-tight">Hub Sentinel</h2>
              <p className="text-sm font-['DM_Sans'] text-white/50 flex-1 leading-relaxed">
                Desktop-first fleet coverage, incident orchestration, and regional risk matrix oversight.
              </p>
              <div className="mt-8 flex items-center text-[var(--color-hub-secondary)] text-xs font-bold uppercase tracking-widest group-hover:translate-x-2 transition-transform duration-300">
                Access Terminal <span className="material-symbols-outlined text-sm ml-1">arrow_forward</span>
              </div>
            </motion.div>
          </Link>

          {/* Admin Card */}
          <Link href="/login/admin" className="block focus:outline-none">
            <motion.div 
              variants={itemVariants}
              whileHover={{ y: -6, transition: { duration: 0.2, ease: "easeOut" } }}
              whileTap={{ scale: 0.98 }}
              className="h-full flex flex-col bg-[var(--color-admin-surface)] border border-[var(--color-admin-outline)]/20 rounded-2xl p-8 relative overflow-hidden group transition-colors hover:border-[var(--color-admin-tertiary)]/40"
            >
              {/* Subtle heavy border-left to hint at Admin KPI style */}
              <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-[var(--color-admin-primary)] to-[var(--color-admin-tertiary)] opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
              <div className="absolute inset-0 bg-gradient-to-b from-[var(--color-admin-primary)]/0 via-transparent to-[var(--color-admin-tertiary)]/5 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
              
              <div className="w-12 h-12 rounded-sm bg-[var(--color-admin-primary)]/10 flex items-center justify-center mb-6 border border-[var(--color-admin-primary)]/20">
                <span className="material-symbols-outlined text-[var(--color-admin-primary)]">terminal</span>
              </div>
              <h2 className="text-2xl font-['Inter'] font-bold text-white mb-3 tracking-tight">The Core</h2>
              <p className="text-sm font-['Inter'] text-white/50 flex-1 leading-relaxed">
                Brutalist command-center interface. Real-time actuarial simulation and terminal-grade data feeds.
              </p>
              <div className="mt-8 flex items-center text-[var(--color-admin-tertiary)] text-[10px] font-['JetBrains_Mono'] uppercase tracking-widest group-hover:translate-x-2 transition-transform duration-300">
                INIT_LOGIN <span className="material-symbols-outlined text-[14px] ml-1">chevron_right</span>
              </div>
            </motion.div>
          </Link>

        </motion.div>
      </motion.div>
    </main>
  );
}
