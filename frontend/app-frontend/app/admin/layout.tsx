import { Header } from "@/components/admin/Header";
import { AdminRouteGuard } from "@/components/admin/AdminRouteGuard";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <AdminRouteGuard>
      <div className="min-h-screen bg-[var(--color-admin-bg)] text-[var(--color-admin-text)] font-['Inter'] flex flex-col relative overflow-hidden selection:bg-[var(--color-admin-primary)]/30 w-full h-screen">
        <Header />
        
        {/* High density scrolling area */}
        <main className="flex-1 overflow-x-hidden overflow-y-auto w-full p-4 md:p-6 lg:p-8 custom-scrollbar max-w-[1600px] mx-auto">
          {children}
        </main>
      </div>
    </AdminRouteGuard>
  );
}
