"use client";

import { motion, AnimatePresence } from "framer-motion";
import { ReactNode } from "react";

// --- RIDER MOTION RULES ---
// Fluid, app-like, opacity + translation Y
export function RiderPageTransition({ children, keyId }: { children: ReactNode, keyId?: string }) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={keyId}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.25, ease: "easeOut" as const }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

// --- HUB MOTION RULES ---
// Crossfades only. No bouncing, no translations on page load.
export function HubPageCrossfade({ children, keyId }: { children: ReactNode, keyId?: string }) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={keyId}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.3, ease: "easeOut" as const }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}

// --- ADMIN MOTION RULES ---
// Brutalist connection feel. Almost instantaneous.
export function AdminInstantLoad({ children, keyId }: { children: ReactNode, keyId?: string }) {
  return (
    <AnimatePresence mode="wait">
      <motion.div
        key={keyId}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.1 }}
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
}
