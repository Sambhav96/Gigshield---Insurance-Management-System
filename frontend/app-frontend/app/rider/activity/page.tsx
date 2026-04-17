"use client";

import { RiderPageTransition } from "@/lib/motion/safeWrappers";
import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import { fetchApi, riderPath } from "@/lib/api/client";

type ActivityItem = {
  id: string;
  type: "payment" | "alert" | "camera" | string;
  title: string;
  subtitle: string;
  val: string;
};

export default function ActivityFeed() {
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function load() {
      setIsLoading(true);
      setError(null);

      const res = await fetchApi<any>(riderPath("/riders/me/activity"), { method: "GET" });
      if (!mounted) return;

      if (res.status === 404 || res.status === 501) {
        setActivities([]);
        setIsLoading(false);
        return;
      }

      if (res.error || !res.data) {
        setError(res.error?.message || "Unable to load activity");
        setActivities([]);
        setIsLoading(false);
        return;
      }

      const activityList = Array.isArray(res.data)
        ? res.data
        : Array.isArray(res.data?.activities)
        ? res.data.activities
        : [];

      const mapped = activityList.map((a: any, idx: number) => ({
        id: String(a.id || idx),
        type: (a.type || "alert") as string,
        title: a.title || "Activity",
        subtitle: a.subtitle || a.description || "Update received",
        val: a.value || a.status || "Logged",
      })) as ActivityItem[];

      setActivities(mapped);
      setIsLoading(false);
    }

    load();
    return () => {
      mounted = false;
    };
  }, []);

  const visualized = useMemo(
    () =>
      activities.map((a) => {
        const color = a.type === "payment"
          ? "text-[var(--color-rider-secondary)]"
          : a.type === "alert"
          ? "text-[var(--color-rider-error)]"
          : "text-[var(--color-rider-primary)]";

        const icon = a.type === "payment"
          ? "payments"
          : a.type === "alert"
          ? "warning"
          : "photo_camera";

        return { ...a, color, icon };
      }),
    [activities]
  );

  return (
    <RiderPageTransition>
      <div className="space-y-6 pt-2">
        <h1 className="text-2xl font-['Space_Grotesk'] font-bold text-white mb-6">Activity Graph</h1>

        {error && (
          <motion.div className="bg-[var(--color-rider-error)]/20 border border-[var(--color-rider-error)] text-[var(--color-rider-error)] text-xs font-['Manrope'] font-medium px-4 py-3 rounded-xl flex items-center gap-2">
            <span className="material-symbols-outlined text-sm">error</span>
            {error}
          </motion.div>
        )}

        <motion.div 
          initial="hidden" animate="visible" transition={{ staggerChildren: 0.05 }}
          className="space-y-3"
        >
          {isLoading && Array.from({ length: 4 }).map((_, i) => (
            <motion.div 
              key={`skeleton-${i}`}
              variants={{ hidden: { opacity: 0, x: -10 }, visible: { opacity: 1, x: 0 } }}
              className="flex items-center justify-between p-4 bg-white/[0.02] border border-white/5 rounded-xl animate-pulse"
            >
              <div className="flex items-center gap-4">
                <div className="p-2 rounded-full bg-white/5 w-10 h-10" />
                <div>
                  <div className="h-4 w-32 bg-white/10 rounded mb-2" />
                  <div className="h-3 w-40 bg-white/10 rounded" />
                </div>
              </div>
              <div className="h-4 w-16 bg-white/10 rounded" />
            </motion.div>
          ))}

          {!isLoading && visualized.length === 0 && (
            <motion.div
              variants={{ hidden: { opacity: 0, x: -10 }, visible: { opacity: 1, x: 0 } }}
              className="flex items-center justify-between p-4 bg-white/[0.02] border border-white/5 rounded-xl"
            >
              <div className="flex items-center gap-4">
                <div className="p-2 rounded-full bg-white/5 text-white/40">
                  <span className="material-symbols-outlined">history</span>
                </div>
                <div>
                  <h4 className="text-sm font-bold text-white">No activity yet</h4>
                  <p className="text-[10px] text-[#a8abb3]">Your recent rider events will appear here.</p>
                </div>
              </div>
              <span className="text-sm font-bold font-['Space_Grotesk'] text-white/60">\u2014</span>
            </motion.div>
          )}

          {!isLoading && visualized.map((a, i) => (
            <motion.div 
              key={a.id || i}
              variants={{ hidden: { opacity: 0, x: -10 }, visible: { opacity: 1, x: 0 } }}
              className="flex items-center justify-between p-4 bg-white/[0.02] border border-white/5 rounded-xl hover:bg-white/[0.05] transition-colors"
            >
              <div className="flex items-center gap-4">
                <div className={`p-2 rounded-full bg-white/5 ${a.color}`}>
                  <span className="material-symbols-outlined">{a.icon}</span>
                </div>
                <div>
                  <h4 className="text-sm font-bold text-white">{a.title}</h4>
                  <p className="text-[10px] text-[#a8abb3]">{a.subtitle}</p>
                </div>
              </div>
              <span className={`text-sm font-bold font-['Space_Grotesk'] ${a.type === 'payment' ? a.color : 'text-white/60'}`}>
                {a.val}
              </span>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </RiderPageTransition>
  );
}
