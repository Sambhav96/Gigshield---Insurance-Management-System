"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cx } from "@/lib/utils/cx";
import { authService } from "@/lib/api/auth";

export function TopNav() {
  const [onShift, setOnShift] = useState(true);
  const router = useRouter();

  const handleLogout = () => {
    authService.logout();
    router.replace("/login/rider");
  };

  return (
    <header className="fixed top-0 w-full z-50 flex justify-between items-center px-6 h-16 bg-[#0a0e14] shadow-[0_8px_32px_rgba(84,199,252,0.15)] bg-gradient-to-b from-white/5 to-transparent">
      <Link href="/rider/profile" className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-full overflow-hidden border border-[var(--color-rider-primary)]/20 p-0.5 bg-[var(--color-rider-primary)]/10 flex items-center justify-center">
          <span className="material-symbols-outlined text-[var(--color-rider-primary)] text-xl">person</span>
        </div>
        <span className="text-xl font-black text-[var(--color-rider-white)] tracking-tighter font-['Syne']">GigShield</span>
      </Link>

      <div className="flex items-center gap-3">
        {/* Live Zone Pulse Toggle */}
        <button
          onClick={() => setOnShift(!onShift)}
          className="flex items-center gap-3 bg-[#1b2028] px-3 py-1.5 rounded-full border border-white/5 cursor-pointer active:scale-95 transition-transform"
        >
          <span className="font-['DM_Sans'] text-[10px] font-bold uppercase tracking-widest text-[#a8abb3]">On Shift</span>
          <div className="relative inline-flex items-center">
            <div className={cx(
              "w-8 h-4 rounded-full transition-all relative",
              onShift ? "bg-[var(--color-rider-secondary)]" : "bg-[#151a21]"
            )}>
              <div className={cx(
                "absolute top-[2px] w-3 h-3 bg-white rounded-full transition-transform duration-300",
                onShift ? "left-[1px] translate-x-[14px]" : "left-[2px]"
              )} />
            </div>
          </div>
        </button>

        {/* Logout */}
        <button
          onClick={handleLogout}
          className="w-8 h-8 rounded-full bg-white/5 border border-white/10 flex items-center justify-center hover:bg-white/10 active:scale-95 transition-all"
          title="Sign out"
        >
          <span className="material-symbols-outlined text-white/50 text-base">logout</span>
        </button>
      </div>
    </header>
  );
}
