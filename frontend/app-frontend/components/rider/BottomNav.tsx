"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { useState } from "react";
import { cx } from "@/lib/utils/cx";
import { CameraRecorder } from "@/components/rider/CameraRecorder";

export function BottomNav() {
  const pathname = usePathname();
  const [cameraOpen, setCameraOpen] = useState(false);

  const isActive = (path: string) => {
    if (path === "/rider" && pathname === "/rider") return true;
    if (path !== "/rider" && pathname.startsWith(path)) return true;
    return false;
  };

  const NavItem = ({ href, icon, label }: { href: string; icon: string; label: string }) => {
    const active = isActive(href);
    return (
      <Link
        href={href}
        className={cx(
          "flex flex-col items-center gap-1 group relative transition-opacity",
          active ? "opacity-100" : "opacity-40 hover:opacity-100"
        )}
      >
        <motion.div whileTap={{ scale: 0.9 }}>
          <span
            className={cx("material-symbols-outlined text-2xl transition-colors", active ? "text-[var(--color-rider-secondary)]" : "text-white")}
            style={active ? { fontVariationSettings: "'FILL' 1, 'wght' 500" } : { fontVariationSettings: "'FILL' 0, 'wght' 400" }}
          >
            {icon}
          </span>
        </motion.div>
        <span className={cx("text-[10px] font-bold tracking-tight uppercase transition-colors", active ? "text-[var(--color-rider-secondary)]" : "text-white")}>
          {label}
        </span>
      </Link>
    );
  };

  return (
    <>
      {/* Camera recorder fullscreen overlay */}
      <AnimatePresence>
        {cameraOpen && <CameraRecorder onClose={() => setCameraOpen(false)} />}
      </AnimatePresence>

      <nav className="fixed bottom-0 left-0 w-full z-50 px-4 pb-6 pt-2 pointer-events-none">
        <div className="max-w-md mx-auto pointer-events-auto bg-[#0a0e14]/90 backdrop-blur-xl rounded-2xl px-6 py-3 flex items-center justify-between relative border border-white/10 shadow-2xl">

          <NavItem href="/rider" icon="home" label="Home" />
          <NavItem href="/rider/activity" icon="bar_chart" label="Activity" />

          {/* Central Camera Button */}
          <div className="relative">
            <div className="absolute -inset-4 bg-[var(--color-rider-primary)]/20 blur-xl rounded-full" />
            <motion.button
              whileTap={{ scale: 0.92 }}
              onClick={() => setCameraOpen(true)}
              aria-label="Record incident video"
              className="relative w-14 h-14 bg-[var(--color-rider-primary)] rounded-full flex items-center justify-center shadow-[0_0_20px_rgba(84,199,252,0.4)]"
            >
              <span className="material-symbols-outlined text-[#002635] text-3xl" style={{ fontVariationSettings: "'FILL' 1" }}>
                photo_camera
              </span>
            </motion.button>
          </div>

          <NavItem href="/rider/earnings" icon="account_balance_wallet" label="Earnings" />
          <NavItem href="/rider/shield" icon="shield" label="Shield" />

        </div>
      </nav>
    </>
  );
}
