import { Sidebar } from "@/components/hub/Sidebar";
import { HubRouteGuard } from "@/components/hub/HubRouteGuard";

export default function HubLayout({ children }: { children: React.ReactNode }) {
  return (
    <HubRouteGuard>
      <div className="min-h-screen bg-[var(--color-hub-bg)] text-[var(--color-hub-text)] font-['DM_Sans'] flex relative overflow-hidden selection:bg-[var(--color-hub-secondary)]/30">
        <div className="hub-grain absolute inset-0 z-0"></div>
        
        {/* Persistent App Sidebar */}
        <Sidebar />
        
        {/* Main Content Area filling remaining space */}
        <main className="ml-64 flex-1 p-8 lg:p-12 h-screen overflow-y-auto relative z-10">
          {children}
        </main>
      </div>
    </HubRouteGuard>
  );
}
