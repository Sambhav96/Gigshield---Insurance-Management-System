"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/lib/utils/cx";

export function Sidebar() {
  const pathname = usePathname();
  
  const navItems = [
    { name: "Live Terminal", href: "/hub", icon: "dashboard" },
    { name: "Fleet Coverage", href: "/hub/fleet-coverage", icon: "group" },
    { name: "Incident Matrix", href: "/hub/incidents", icon: "emergency" },
  ];

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-64 bg-[var(--color-hub-bg)] border-r border-[#11131c] z-50 flex flex-col pt-8 pb-6 px-4">
      {/* Brand Header */}
      <div className="px-4 mb-12 flex items-center gap-3">
        <span className="material-symbols-outlined text-[var(--color-hub-secondary)] text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>hub</span>
        <h1 className="text-xl font-['Syne'] font-black text-white tracking-widest uppercase">Sentinel</h1>
      </div>
      
      {/* Deep Navigation */}
      <nav className="flex-1 space-y-1.5">
        {navItems.map((item) => {
          const active = item.href === "/hub" ? pathname === "/hub" : pathname.startsWith(item.href);
          return (
            <Link key={item.name} href={item.href} className={cx(
              "flex items-center gap-4 px-4 py-3 rounded-xl transition-all duration-300 group",
              active ? "bg-[var(--color-hub-surface-high)]" : "hover:bg-[var(--color-hub-surface-low)]"
            )}>
              <span className={cx(
                "material-symbols-outlined text-[20px] transition-colors",
                active ? "text-[var(--color-hub-secondary)]" : "text-[var(--color-hub-text)]/40 group-hover:text-[var(--color-hub-text)]/70"
              )} style={active ? { fontVariationSettings: "'FILL' 1" } : {}}>
                {item.icon}
              </span>
              <span className={cx(
                "font-['DM_Sans'] text-sm transition-colors",
                active ? "text-white font-bold" : "text-[var(--color-hub-text)]/60 font-medium group-hover:text-white"
              )}>
                {item.name}
              </span>
            </Link>
          );
        })}
      </nav>

      {/* Operator Hub Node Status */}
      <div className="mt-8 bg-[var(--color-hub-surface-low)] rounded-xl p-4 flex items-center gap-3 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-16 h-16 bg-[var(--color-hub-secondary)]/10 blur-xl rounded-full" />
        <div className="w-10 h-10 rounded-full bg-[var(--color-hub-surface-high)] flex items-center justify-center border border-[var(--color-hub-secondary)]/10 relative z-10">
          <span className="material-symbols-outlined text-[var(--color-hub-secondary)] text-sm">shield_person</span>
        </div>
        <div className="relative z-10">
          <p className="text-sm font-bold text-white font-['Syne']">Sector Alpha</p>
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-hub-secondary)]" />
            <p className="text-[10px] text-[var(--color-hub-secondary)] font-['DM_Sans'] font-medium uppercase tracking-widest">Active Node</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
