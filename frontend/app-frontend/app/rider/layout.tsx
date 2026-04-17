import type { Metadata, Viewport } from "next";
import { TopNav } from "@/components/rider/TopNav";
import { BottomNav } from "@/components/rider/BottomNav";
import { ServicerWorkerRegistrar } from "@/components/rider/ServicerWorkerRegistrar";
import { RiderRouteGuard } from "@/components/rider/RiderRouteGuard";

export const viewport: Viewport = {
  themeColor: "#0a0e14",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover", // Forces UI cleanly through notches
};

export const metadata: Metadata = {
  title: 'GigShield | Active Shift',
  description: 'PWA terminal for active logistic deployment.',
  manifest: '/manifest.webmanifest',
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "GS Rider",
  },
  formatDetection: {
    telephone: false,
  }
};

export default function RiderLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--color-rider-bg)] text-[var(--color-rider-white)] font-['Manrope'] selection:bg-[var(--color-rider-primary)]/30 overscroll-none">
      <RiderRouteGuard>
        <ServicerWorkerRegistrar />
        <TopNav />
        {/* 
          Rider is strictly mobile-first. 
          It forces rendering inside a max-w-md constraint to simulate the PWA viewport identically on desktop 
        */}
        <div className="pt-20 pb-28 px-4 max-w-md mx-auto relative min-h-screen">
          {children}
        </div>
        <BottomNav />
      </RiderRouteGuard>
    </div>
  );
}
