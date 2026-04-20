/**
 * Sidebar — Navigation + History
 * Giao diện giống Gemini (dark, minimal)
 */
"use client";
import { useStore, type HistoryJob } from "@/lib/store";
import { useRouter } from "next/navigation";

const MODEL_LABELS: Record<string, string> = {
  veo31_fast_lp: "Veo 3.1 Fast LP",
  veo31_fast: "Veo 3.1 Fast",
  veo31_quality: "Veo 3.1 Quality",
  veo2_fast: "Veo 2 Fast",
  veo2_quality: "Veo 2 Quality",
};

const MODEL_PRICES: Record<string, number> = {
  veo31_fast_lp: 5000, veo31_fast: 8000, veo31_quality: 12000,
  veo2_fast: 3000, veo2_quality: 6000,
};

export function Sidebar() {
  const user = useStore((s) => s.user);
  const history = useStore((s) => s.history);
  const logout = useStore((s) => s.logout);
  const router = useRouter();

  // Nhóm history theo ngày
  const today = new Date().toDateString();
  const yesterday = new Date(Date.now() - 86400000).toDateString();

  const grouped = history.reduce((acc, job) => {
    const d = new Date(job.created_at).toDateString();
    const label = d === today ? "Hôm nay" : d === yesterday ? "Hôm qua" : new Date(job.created_at).toLocaleDateString("vi-VN");
    if (!acc[label]) acc[label] = [];
    acc[label].push(job);
    return acc;
  }, {} as Record<string, HistoryJob[]>);

  return (
    <aside className="sidebar flex flex-col" style={{ background: "var(--bg-secondary)" }}>
      {/* Header */}
      <div className="p-4 border-b" style={{ borderColor: "var(--border-subtle)" }}>
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: "var(--accent-gradient)" }}>
            <span className="text-sm font-bold text-black">V3</span>
          </div>
          <div>
            <h1 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Veo3 Studio</h1>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>AI Video Generation</p>
          </div>
        </div>
      </div>

      {/* New Video button */}
      <div className="p-3">
        <button
          onClick={() => {/* scroll to prompt */}}
          className="w-full flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all"
          style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border-subtle)" }}
          onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg-hover)"}
          onMouseLeave={(e) => e.currentTarget.style.background = "var(--bg-tertiary)"}
        >
          <span className="material-symbols-rounded text-lg" style={{ color: "var(--accent-blue)" }}>add</span>
          Tạo video mới
        </button>
      </div>

      {/* History */}
      <div className="flex-1 overflow-y-auto px-2">
        {Object.entries(grouped).map(([label, jobs]) => (
          <div key={label} className="mb-3">
            <p className="px-3 py-1.5 text-xs font-medium" style={{ color: "var(--text-muted)" }}>{label}</p>
            {jobs.map((job) => (
              <button
                key={job.id}
                className="w-full text-left px-3 py-2 rounded-lg text-sm transition-colors mb-0.5 flex items-center gap-2"
                style={{ color: "var(--text-secondary)" }}
                onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg-hover)"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
              >
                <span className="material-symbols-rounded text-base" style={{
                  color: job.status === "completed" ? "var(--success)" :
                         job.status === "failed" ? "var(--error)" : "var(--accent-blue)"
                }}>
                  {job.status === "completed" ? "check_circle" : job.status === "failed" ? "error" : "pending"}
                </span>
                <span className="truncate flex-1">{job.prompt.slice(0, 40)}</span>
              </button>
            ))}
          </div>
        ))}
        {history.length === 0 && (
          <div className="px-3 py-8 text-center">
            <span className="material-symbols-rounded text-3xl mb-2 block" style={{ color: "var(--text-muted)" }}>
              movie_creation
            </span>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>Chưa có video nào</p>
          </div>
        )}
      </div>

      {/* User info */}
      {user && (
        <div className="p-3 border-t" style={{ borderColor: "var(--border-subtle)" }}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold"
                style={{ background: "var(--bg-tertiary)", color: "var(--accent-blue)" }}>
                {user.username[0].toUpperCase()}
              </div>
              <div>
                <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{user.username}</p>
                <p className="text-xs" style={{ color: "var(--accent-blue)" }}>{(user.balance ?? 0).toLocaleString()} credits</p>
              </div>
            </div>
            <button
              onClick={() => { logout(); router.push("/login"); }}
              className="p-1.5 rounded-lg transition-colors"
              style={{ color: "var(--text-muted)" }}
              onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg-hover)"}
              onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
              title="Đăng xuất"
            >
              <span className="material-symbols-rounded text-lg">logout</span>
            </button>
          </div>
        </div>
      )}
    </aside>
  );
}
