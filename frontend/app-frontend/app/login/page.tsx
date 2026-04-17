"use client";

import { motion, Variants } from "framer-motion";
import Link from "next/link";
import { RiderPageTransition, AdminInstantLoad, HubPageCrossfade } from "@/lib/motion/safeWrappers";

export default function RoleSelector() {
  const containerVariants: Variants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { staggerChildren: 0.1 } },
  };
  const itemVariants: Variants = {
    hidden: { opacity: 0, y: 10 },
    visible: { opacity: 1, y: 0, transition: { duration: 0.3 } },
  };

  return (
    <main className="min-h-screen bg-black text-white flex flex-col items-center justify-center p-6 font-['Inter'] relative overflow-hidden">
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-2xl h-[400px] bg-white/5 blur-[120px] rounded-full pointer-events-none" />
      
      <motion.div 
        className="z-10 w-full max-w-3xl space-y-12"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
      >
        <motion.div variants={itemVariants} className="text-center">
          <h1 className="text-3xl font-['Syne'] font-bold mb-3">Authentication Protocol</h1>
          <p className="text-white/50 text-sm">Please select your operational portal to proceed.</p>
        </motion.div>

        <motion.div variants={containerVariants} className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Link href="/login/rider" className="block focus:outline-none focus:ring-2 focus:ring-[var(--color-rider-primary)] rounded-2xl">
            <motion.div 
              variants={itemVariants}
              whileHover={{ y: -4 }}
              whileTap={{ scale: 0.98 }}
              className="p-6 rounded-2xl bg-[var(--color-rider-bg)] border border-white/5 hover:border-[var(--color-rider-primary)]/50 transition-colors flex flex-col items-center text-center space-y-4"
            >
              <div className="w-12 h-12 rounded-full bg-[var(--color-rider-primary)]/10 flex items-center justify-center">
                <span className="material-symbols-outlined text-[var(--color-rider-primary)]">motorcycle</span>
              </div>
              <h2 className="text-lg font-['Space_Grotesk'] font-bold">Rider PWA</h2>
            </motion.div>
          </Link>

          <Link href="/login/hub-manager" className="block focus:outline-none focus:ring-2 focus:ring-[var(--color-hub-secondary)] rounded-2xl">
            <motion.div 
              variants={itemVariants}
              whileHover={{ y: -4 }}
              whileTap={{ scale: 0.98 }}
              className="p-6 rounded-2xl bg-[var(--color-hub-surface-low)] border border-white/5 hover:border-[var(--color-hub-secondary)]/50 transition-colors flex flex-col items-center text-center space-y-4"
            >
              <div className="w-12 h-12 rounded-xl bg-[var(--color-hub-secondary)]/10 flex items-center justify-center">
                <span className="material-symbols-outlined text-[var(--color-hub-secondary)]">hub</span>
              </div>
              <h2 className="text-lg font-['Syne'] font-bold">Hub Sentinel</h2>
            </motion.div>
          </Link>

          <Link href="/login/admin" className="block focus:outline-none focus:ring-2 focus:ring-[var(--color-admin-primary)] rounded-lg">
            <motion.div 
              variants={itemVariants}
              whileHover={{ y: -4 }}
              whileTap={{ scale: 0.98 }}
              className="p-6 rounded-lg bg-[var(--color-admin-surface)] border-l-4 border-[var(--color-admin-outline)]/20 border-t border-b border-r border-[#ffffff05] hover:border-l-[var(--color-admin-primary)] transition-colors flex flex-col items-center text-center space-y-4"
            >
              <div className="w-12 h-12 rounded-sm bg-[var(--color-admin-primary)]/10 flex items-center justify-center border border-[var(--color-admin-primary)]/20">
                <span className="material-symbols-outlined text-[var(--color-admin-primary)]">terminal</span>
              </div>
              <h2 className="text-lg font-['Inter'] font-bold">The Core</h2>
            </motion.div>
          </Link>
        </motion.div>
      </motion.div>
    </main>
  );
}
