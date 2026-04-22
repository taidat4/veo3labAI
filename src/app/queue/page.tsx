/**
 * Queue Page — Danh sách chờ xử lý
 */
"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import { useWebSocket } from "@/lib/useWebSocket";
import { Navbar } from "@/components/Navbar";
import { Toast } from "@/components/Toast";

export default function QueuePage() {
  const router = useRouter();
  const user = useStore((s) => s.user);
  const setUser = useStore((s) => s.setUser);
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useWebSocket();

  useEffect(() => {
    const stored = localStorage.getItem("veo3_user");
    const token = localStorage.getItem("veo3_token");
    if (stored && token) {
      setUser({ ...JSON.parse(stored), token });
    } else {
      router.push("/login");
    }
  }, [router, setUser]);

  const fetchJobs = useCallback(async () => {
    try {
      const data = await api.getJobs(50);
      setJobs((data.jobs || []).filter((j: any) =>
        ["waiting", "queued", "pending", "processing"].includes(j.status)
      ));
    } catch {} finally { setLoading(false); }
  }, []);

  useEffect(() => { if (user) fetchJobs(); }, [user, fetchJobs]);

  // Auto-refresh
  useEffect(() => {
    if (!user) return;
    const interval = setInterval(fetchJobs, 4000);
    return () => clearInterval(interval);
  }, [user, fetchJobs]);

  if (!user) return null;

  const statusConfig: Record<string, { icon: string; label: string; color: string }> = {
    waiting: { icon: "schedule", label: "Chờ slot", color: "var(--text-muted)" },
    queued: { icon: "hourglass_top", label: "Đang chờ", color: "var(--warning)" },
    pending: { icon: "pending", label: "Chuẩn bị", color: "var(--neon-blue)" },
    processing: { icon: "movie_creation", label: "Đang tạo", color: "var(--neon-purple)" },
  };

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Toast />
      <Navbar />
      <main className="pt-16 px-6 max-w-4xl mx-auto">
        <div className="py-8">
          <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>Queue</h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
            {jobs.length} video đang xử lý
          </p>
        </div>

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="glass-card p-4 flex items-center gap-4">
                <div className="w-10 h-10 shimmer rounded-xl" />
                <div className="flex-1">
                  <div className="h-4 w-3/4 shimmer rounded mb-2" />
                  <div className="h-3 w-1/3 shimmer rounded" />
                </div>
              </div>
            ))}
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-20">
            <span className="material-symbols-rounded text-5xl mb-4 block" style={{ color: "var(--text-muted)" }}>
              check_circle
            </span>
            <p className="text-lg font-medium" style={{ color: "var(--text-secondary)" }}>Queue trống</p>
            <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>Tất cả video đã xử lý xong</p>
          </div>
        ) : (
          <div className="space-y-3 pb-12">
            {jobs.map((job, index) => {
              const cfg = statusConfig[job.status] || statusConfig.queued;
              return (
                <div key={job.id} className="glass-card p-4 flex items-center gap-4 fade-in">
                  {/* Position */}
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 text-sm font-bold"
                    style={{ background: "var(--gradient-subtle)", color: "var(--neon-blue)" }}>
                    #{index + 1}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>{job.prompt}</p>
                    <div className="flex items-center gap-3 mt-1">
                      <span className="flex items-center gap-1 text-xs" style={{ color: cfg.color }}>
                        <span className="material-symbols-rounded text-sm">{cfg.icon}</span>
                        {cfg.label}
                      </span>
                      <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                        Job #{index + 1}
                      </span>
                    </div>
                  </div>

                  {/* Progress */}
                  <div className="text-right shrink-0">
                    <span className="text-lg font-bold gradient-text">{job.progress_percent || 0}%</span>
                    <div className="w-24 progress-bar mt-1">
                      <div className="progress-fill" style={{ width: `${Math.max(job.progress_percent || 0, 5)}%` }} />
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
}
