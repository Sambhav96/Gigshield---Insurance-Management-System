"use client";

import { RiderPageTransition } from "@/lib/motion/safeWrappers";
import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { fetchApi, riderPath } from "@/lib/api/client";
import { RiderProfileResponse } from "@/lib/api/types";
import { authService } from "@/lib/api/auth";

export default function ProfilePage() {
  const router = useRouter();
  const [rider, setRider] = useState<RiderProfileResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function load() {
      setIsLoading(true);
      setError(null);

      const res = await fetchApi<RiderProfileResponse>(riderPath("/riders/me"), { method: "GET" });
      if (!mounted) return;

      if (res.error || !res.data) {
        setError(res.error?.message || "Unable to load profile");
        setRider(null);
        setIsLoading(false);
        return;
      }

      setRider(res.data);
      setIsLoading(false);
    }

    load();
    return () => {
      mounted = false;
    };
  }, []);

  const initials = useMemo(() => {
    const name = rider?.name?.trim();
    if (!name) return "RS";
    const parts = name.split(/\s+/).filter(Boolean);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0] || ""}${parts[1][0] || ""}`.toUpperCase();
  }, [rider?.name]);

  const identityMeta = useMemo(() => {
    const city = rider?.city || "Unknown City";
    const risk = rider?.risk_profile || "Unknown";
    return `${city} • ${risk}`;
  }, [rider?.city, rider?.risk_profile]);

  const handleSignOut = () => {
    authService.logout();
    router.push("/login");
  };

  return (
    <RiderPageTransition>
      <div className="space-y-8 pt-4">
        {error && (
          <motion.div className="bg-[var(--color-rider-error)]/20 border border-[var(--color-rider-error)] text-[var(--color-rider-error)] text-xs font-['Manrope'] font-medium px-4 py-3 rounded-xl flex items-center gap-2">
            <span className="material-symbols-outlined text-sm">error</span>
            {error}
          </motion.div>
        )}

        {isLoading && (
          <div className="fixed inset-0 z-[999] bg-[var(--color-rider-bg)] flex items-center justify-center">
            <div className="flex flex-col items-center gap-4">
              <span className="material-symbols-outlined animate-spin text-[var(--color-rider-primary)] text-4xl">autorenew</span>
              <p className="text-white/30 text-xs font-['Manrope'] tracking-widest uppercase">Loading profile</p>
            </div>
          </div>
        )}
        
        {/* Identity Head */}
        <div className="flex flex-col items-center justify-center text-center">
          <div className="w-24 h-24 rounded-full overflow-hidden border-2 border-[var(--color-rider-primary)]/40 p-1 mb-4 shadow-[0_0_30px_rgba(84,199,252,0.15)] relative bg-white/5 flex items-center justify-center">
            <span className="text-2xl font-['Space_Grotesk'] font-bold text-[var(--color-rider-primary)]">{initials}</span>
            {/* Status indicator */}
            <div className="absolute bottom-2 right-2 w-4 h-4 bg-[var(--color-rider-secondary)] rounded-full border-2 border-[#0a0e14]"></div>
          </div>
          <h1 className="text-2xl font-['Space_Grotesk'] font-bold text-white">{rider?.name || "Rider"}</h1>
          <p className="text-sm font-['Manrope'] text-white/50">Verified Partner • {identityMeta}</p>
        </div>

        {/* Options */}
        <motion.div className="space-y-2">
          {["Account Details", "Payout Configuration", "Telematics Settings", "Help & Support"].map((item, i) => (
            <motion.button 
              key={i}
              whileTap={{ scale: 0.98, backgroundColor: "rgba(255,255,255,0.05)" }}
              className="w-full p-4 flex items-center justify-between rider-glass-card rounded-2xl border border-white/5 text-left"
            >
              <span className="text-sm font-bold text-white">{item}</span>
              <span className="material-symbols-outlined text-white/40">chevron_right</span>
            </motion.button>
          ))}

          {/* Destructive Option */}
          <motion.button 
            whileTap={{ scale: 0.98 }}
            onClick={handleSignOut}
            className="w-full p-4 flex items-center justify-between bg-red-500/10 rounded-2xl border border-red-500/20 text-left mt-6"
          >
            <span className="text-sm font-bold text-red-500">Sign Out</span>
            <span className="material-symbols-outlined text-red-500">logout</span>
          </motion.button>
        </motion.div>

      </div>
    </RiderPageTransition>
  );
}
