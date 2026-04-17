"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { cx } from "@/lib/utils/cx";
import { authService } from "@/lib/api/auth";

export function Header() {
  const pathname = usePathname();
  const router = useRouter();

  const tabs = [
    { name: "OVERVIEW",    path: "/admin" },
    { name: "FRAUD_QUEUE", path: "/admin/claims" },     // was CLAIMS_DB
    { name: "EXPERIMENTS", path: "/admin/actuarial" },  // was ACTUARIAL_MODEL
    { name: "LAB",         path: "/admin/lab" },        // was DATA_LAB
    { name: "BACKTESTING", path: "/admin/simulation" }, // was SIMULATION
  ];

  const handleLogout = () => {
    authService.logout();
    router.replace("/login/admin");
  };

  return (
    <header className="bg-[var(--color-admin-surface)] border-b border-[var(--color-admin-outline)]/40 h-14 flex items-center px-4 justify-between select-none">
      <div className="flex items-center gap-6 h-full">
        {/* Logo / Root Node */}
        <div className="flex items-center gap-2 pr-6 border-r border-[var(--color-admin-outline)]/40 h-full">
          <span className="material-symbols-outlined text-[var(--color-admin-primary)]">terminal</span>
          <span className="font-['Inter'] font-black text-white tracking-widest uppercase">The Core</span>
        </div>

        {/* Console Tabs */}
        <nav className="flex items-center h-full gap-1">
          {tabs.map((tab) => {
            const isActive = tab.path === "/admin" ? pathname === "/admin" : pathname.startsWith(tab.path);
            return (
              <Link
                key={tab.name}
                href={tab.path}
                className={cx(
                  "h-full px-4 flex items-center border-b-2 text-[11px] font-['JetBrains_Mono'] font-bold tracking-widest transition-colors",
                  isActive
                    ? "border-[var(--color-admin-primary)] text-[var(--color-admin-primary)] bg-[var(--color-admin-primary)]/5"
                    : "border-transparent text-[var(--color-admin-text)]/50 hover:bg-white/5 hover:text-white"
                )}
              >
                {tab.name}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Right: Status + Logout */}
      <div className="flex items-center gap-4 h-full border-l border-[var(--color-admin-outline)]/40 pl-6">
        <div className="flex flex-col text-right">
          <span className="text-[9px] font-['JetBrains_Mono'] text-[var(--color-admin-primary)] uppercase">System Status</span>
          <span className="text-[10px] font-['JetBrains_Mono'] text-white">NOMINAL_0x99A</span>
        </div>
        <div className="w-1.5 h-1.5 rounded-full bg-[var(--color-admin-primary)] animate-pulse"></div>
        <button
          onClick={handleLogout}
          className="ml-2 text-[10px] font-['JetBrains_Mono'] text-[var(--color-admin-outline)] hover:text-[var(--color-admin-error)] border border-[var(--color-admin-outline)]/30 hover:border-[var(--color-admin-error)]/50 px-3 py-1 transition-colors uppercase tracking-widest"
          title="Logout"
        >
          EXIT
        </button>
      </div>
    </header>
  );
}
