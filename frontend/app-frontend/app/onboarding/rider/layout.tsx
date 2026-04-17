import type { Metadata, Viewport } from "next";
// Note: RiderRouteGuard is intentionally NOT placed here.
// Onboarding routes only require an authenticated session (checked by the guard inside /rider layout).
// Placing the guard here caused: Guard sees no policy → redirects to /onboarding → layout renders guard → infinite loop.
// Auth-only check is light and handled by each onboarding form component if needed.

export const viewport: Viewport = {
  themeColor: "#0a0e14",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
};

export const metadata: Metadata = {
  title: "GigShield | Rider Setup",
  description: "Onboarding terminal for new logistic deployment.",
};

export default function OnboardingRiderLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--color-rider-bg)] text-[var(--color-rider-white)] font-['Manrope'] selection:bg-[var(--color-rider-primary)]/30 overscroll-none">
      <div className="pt-8 pb-safe-bottom px-6 max-w-md mx-auto relative min-h-screen flex flex-col">
        {children}
      </div>
    </div>
  );
}
