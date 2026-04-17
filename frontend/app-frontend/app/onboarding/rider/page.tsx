"use client";

import { useSearchParams, useRouter } from "next/navigation";
import { Suspense, useEffect } from "react";
import { RiderPageTransition } from "@/lib/motion/safeWrappers";
import { ProfileForm } from "@/components/rider/onboarding/ProfileForm";
import { PayoutForm } from "@/components/rider/onboarding/PayoutForm";
import { PolicySelectionForm } from "@/components/rider/onboarding/PolicySelectionForm";
import { onboardingService } from "@/lib/api/onboarding";

function OnboardingContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const step = searchParams.get("step") || "profile";
  
  useEffect(() => {
    // Incomplete onboarding resume / refresh persistence tracking
    if (!searchParams.has("step")) {
       let mounted = true;
       onboardingService.getRiderProfile().then(profileRes => {
         if (!mounted) return;
         if (!profileRes.error && profileRes.data) {
          const riderData = profileRes.data as any;
          // Check payout destination from backend (not localStorage)
          if (!riderData.razorpay_fund_account_id) {
            router.replace("/onboarding/rider?step=payout");
          } else {
            onboardingService.getPolicy().then(policyRes => {
              if (!mounted) return;
              if (!policyRes.error && policyRes.data?.status === "active") {
                router.replace("/rider");
                return;
              }
              router.replace("/onboarding/rider?step=policy");
            });
          }
         }
       });
       return () => { mounted = false; };
    }
  }, [searchParams, router]);

  const steps = ["profile", "payout", "policy"];
  const currentIndex = steps.indexOf(step);

  return (
    <RiderPageTransition keyId={step}>
      <div className="flex-1 flex flex-col pt-8 min-h-[80vh]">
        <h1 className="text-3xl font-['Space_Grotesk'] font-bold tracking-tight mb-2">
          {step === "profile" && "Build Profile"}
          {step === "payout" && "Connect Bank"}
          {step === "policy" && "Activate Hub Shield"}
        </h1>
        <p className="text-white/40 text-sm font-['Manrope'] mb-8">
          {step === "profile" && "Enter your professional details to align with your platform."}
          {step === "payout" && "Link an active withdrawal account to securely receive instant payouts."}
          {step === "policy" && "Connect to your operational hub to view live premiums."}
        </p>
        
        <div className="flex justify-between items-center bg-white/5 border border-white/10 rounded-2xl p-4 mb-8 relative overflow-hidden">
          {currentIndex > 0 && (
            <div className="absolute top-0 right-0 w-24 h-24 bg-[var(--color-rider-primary)]/10 blur-[40px] rounded-full pointer-events-none" />
          )}
          <div className="flex items-center gap-3 relative z-10">
            <div className="w-10 h-10 rounded-full bg-[var(--color-rider-primary)]/10 flex items-center justify-center border border-[var(--color-rider-primary)]/20 shadow-[0_0_15px_rgba(84,199,252,0.1)]">
              <span className="material-symbols-outlined text-[var(--color-rider-primary)] text-[20px]" style={{ fontVariationSettings: "'FILL' 1" }}>
                 {step === 'profile' ? 'person' : step === 'payout' ? 'account_balance' : 'shield'}
              </span>
            </div>
            <div>
              <p className="text-[10px] text-white/40 tracking-widest uppercase font-bold mb-0.5 font-['Manrope']">Step {currentIndex + 1} of 3</p>
              <p className="text-sm font-['Space_Grotesk'] text-white font-bold">
                 {step === 'profile' && 'Professional Profile'}
                 {step === 'payout' && 'Payout Settings'}
                 {step === 'policy' && 'Shield Configuration'}
              </p>
            </div>
          </div>
          <div className="flex gap-1.5 relative z-10">
            {steps.map((s, i) => (
              <div key={s} className={`h-1.5 rounded-full transition-all duration-500 ease-out ${i <= currentIndex ? 'w-4 bg-[var(--color-rider-primary)] shadow-[0_0_8px_rgba(84,199,252,0.4)]' : 'w-1.5 bg-white/20'}`} />
            ))}
          </div>
        </div>

        {step === "profile" && <ProfileForm />}
        {step === "payout" && <PayoutForm />}
        {step === "policy" && <PolicySelectionForm />}
      </div>
    </RiderPageTransition>
  );
}

export default function RiderOnboarding() {
  return (
    <Suspense fallback={<div className="h-full flex items-center justify-center text-[var(--color-rider-primary)]"><span className="material-symbols-outlined animate-spin text-2xl">autorenew</span></div>}>
      <OnboardingContent />
    </Suspense>
  );
}
