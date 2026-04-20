/**
 * Admin Dashboard — Manage Ultra Accounts
 * Features: countdown timer, per-account stats modal, load balancing view
 */
"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { useStore } from "@/lib/store";
import { adminApi } from "@/lib/api";
import { Toast } from "@/components/Toast";

interface Account {
  id: number;
  email: string;
  status: string;
  is_enabled: boolean;
  health_score: number;
  usage_count: number;
  current_concurrent: number;
  max_concurrent: number;
  has_token: boolean;
  bearer_token?: string;
  token_expires_at?: string;
  last_used_at?: string;
  last_refresh_at?: string;
  proxy_url?: string;
  flow_project_url?: string;
  cookies?: string;
}

interface PoolStats {
  total_accounts: number;
  healthy_accounts: number;
  total_capacity: number;
  total_used: number;
  available: number;
  avg_health: number;
  accounts: Account[];
}

interface AccountStats {
  account_id: number;
  email: string;
  total_jobs: number;
  successful: number;
  failed: number;
  active: number;
  success_rate: number;
  daily: { date: string; success: number; failed: number }[];
  recent_jobs: { id: number; prompt: string; status: string; error?: string; created_at?: string; finished_at?: string }[];
}

/* ═══ Countdown Timer Component — 3 tier colors ═══ */
function CountdownTimer({ expiresAt }: { expiresAt: string }) {
  const [timeLeft, setTimeLeft] = useState("");
  const [tier, setTier] = useState<"green" | "yellow" | "red" | "expired">("green");
  const [pct, setPct] = useState(100);
  const TOTAL_DURATION = 55 * 60 * 1000; // 55 min total token life

  useEffect(() => {
    const update = () => {
      const now = Date.now();
      const expires = new Date(expiresAt).getTime();
      const diff = expires - now;

      if (diff <= 0) {
        setTimeLeft("HẾT HẠN");
        setTier("expired");
        setPct(0);
        return;
      }

      // 3 tiers: green > 20min, yellow 5-20min, red < 5min
      const minutes = diff / 60000;
      if (minutes > 20) setTier("green");
      else if (minutes > 5) setTier("yellow");
      else setTier("red");

      setPct(Math.min(100, (diff / TOTAL_DURATION) * 100));

      const h = Math.floor(diff / 3600000);
      const m = Math.floor((diff % 3600000) / 60000);
      const s = Math.floor((diff % 60000) / 1000);
      setTimeLeft(
        `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
      );
    };

    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [expiresAt]);

  const colorMap = {
    green: "var(--success)",
    yellow: "var(--warning)",
    red: "var(--error)",
    expired: "var(--error)",
  };
  const color = colorMap[tier];

  return (
    <div className="flex flex-col gap-0.5 min-w-[80px]">
      <span
        className="font-mono text-xs font-semibold"
        style={{
          color,
          animation: tier === "red" ? "pulse 1s infinite" : tier === "expired" ? "pulse 0.5s infinite" : "none",
        }}
      >
        {tier === "expired" ? "⚠️ HẾT HẠN" : `⏱ ${timeLeft}`}
      </span>
      <div className="w-full h-1 rounded-full overflow-hidden" style={{ background: "var(--bg-tertiary)" }}>
        <div
          className="h-full rounded-full transition-all duration-1000"
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  );
}



/* ═══ Stats Modal Component ═══ */
function StatsModal({ accountId, onClose }: { accountId: number; onClose: () => void }) {
  const [stats, setStats] = useState<AccountStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const data = await adminApi.getAccountStats(accountId);
        setStats(data as AccountStats);
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    })();
  }, [accountId]);

  if (loading) {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }} onClick={onClose}>
        <div className="spinner spinner-lg"></div>
      </div>
    );
  }

  if (!stats) return null;

  const maxDaily = Math.max(...stats.daily.map(d => d.success + d.failed), 1);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
      onClick={onClose}>
      <div className="w-full max-w-md max-h-[75vh] overflow-y-auto rounded-xl p-4" onClick={e => e.stopPropagation()}
        style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", boxShadow: "0 8px 32px rgba(0,0,0,0.4)" }}>

        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="min-w-0">
            <h2 className="text-sm font-bold truncate" style={{ color: "var(--text-primary)" }}>
              <span className="material-symbols-rounded text-base mr-1.5 align-middle" style={{ color: "var(--neon-blue)" }}>analytics</span>
              {stats.email}
            </h2>
          </div>
          <button onClick={onClose} className="btn-ghost !p-1.5 !rounded-full flex-shrink-0">
            <span className="material-symbols-rounded text-lg" style={{ color: "var(--text-muted)" }}>close</span>
          </button>
        </div>

        {/* Stats Cards — compact row */}
        <div className="grid grid-cols-4 gap-2 mb-3">
          {[
            { label: "Tổng", value: stats.total_jobs, icon: "work", color: "var(--neon-blue)" },
            { label: "OK", value: stats.successful, icon: "check_circle", color: "var(--success)" },
            { label: "Lỗi", value: stats.failed, icon: "cancel", color: "var(--error)" },
            { label: "Tỷ lệ", value: `${stats.success_rate}%`, icon: "trending_up", color: "var(--neon-purple)" },
          ].map((s, i) => (
            <div key={i} className="rounded-lg p-2 text-center" style={{ background: `${s.color}10` }}>
              <span className="material-symbols-rounded text-lg block" style={{ color: s.color }}>{s.icon}</span>
              <p className="text-base font-bold" style={{ color: "var(--text-primary)" }}>{s.value}</p>
              <p className="text-[9px]" style={{ color: "var(--text-muted)" }}>{s.label}</p>
            </div>
          ))}
        </div>

        {/* Compact success bar */}
        <div className="mb-3 rounded-lg p-2" style={{ background: "var(--bg-tertiary)" }}>
          <div className="flex items-center justify-between text-[10px] mb-1" style={{ color: "var(--text-muted)" }}>
            <span>✅ {stats.successful} thành công</span>
            <span>❌ {stats.failed} thất bại</span>
            <span>🔄 {stats.active} đang xử lý</span>
          </div>
          <div className="w-full h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-primary)" }}>
            <div className="h-full rounded-full" style={{ width: `${stats.success_rate}%`, background: "linear-gradient(90deg, var(--success), var(--neon-cyan))" }} />
          </div>
        </div>

        {/* Bar Chart — 7 Days */}
        <div className="mb-3">
          <h3 className="text-xs font-semibold mb-2" style={{ color: "var(--text-secondary)" }}>
            📊 7 ngày gần nhất
          </h3>
          <div className="flex items-end gap-1 h-12">
            {stats.daily.map((d, i) => (
              <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
                <div className="w-full flex flex-col-reverse gap-[1px]" style={{ height: "36px" }}>
                  {d.success + d.failed > 0 && (
                    <>
                      <div className="w-full rounded-t-sm" style={{
                        height: `${(d.success / maxDaily) * 100}%`,
                        background: "var(--success)",
                        minHeight: d.success > 0 ? "2px" : "0",
                      }} title={`✅ ${d.success}`} />
                      <div className="w-full rounded-t-sm" style={{
                        height: `${(d.failed / maxDaily) * 100}%`,
                        background: "var(--error)",
                        minHeight: d.failed > 0 ? "2px" : "0",
                      }} title={`❌ ${d.failed}`} />
                    </>
                  )}
                </div>
                <span className="text-[8px]" style={{ color: "var(--text-muted)" }}>{d.date}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Recent Jobs */}
        {stats.recent_jobs.length > 0 && (
          <div>
            <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text-primary)" }}>
              <span className="material-symbols-rounded text-base mr-1 align-middle" style={{ color: "var(--neon-purple)" }}>history</span>
              Jobs gần đây
            </h3>
            <div className="space-y-1 max-h-36 overflow-y-auto">
              {stats.recent_jobs.slice(0, 6).map(j => (
                <div key={j.id} className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-xs"
                  style={{ background: "var(--bg-tertiary)" }}>
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{
                    background: j.status === "completed" ? "var(--success)" : j.status === "failed" ? "var(--error)" : "var(--warning)"
                  }} />
                  <span className="flex-1 truncate" style={{ color: "var(--text-secondary)" }}>{j.prompt}</span>
                  <span className="flex-shrink-0 font-mono" style={{ color: "var(--text-muted)", fontSize: "10px" }}>
                    #{j.id}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ═══ Main Admin Page ═══ */
export default function AdminPage() {
  const router = useRouter();
  const showToast = useStore((s) => s.showToast);

  const [authed, setAuthed] = useState(false);
  const [secretInput, setSecretInput] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState("");

  const [stats, setStats] = useState<PoolStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [addForm, setAddForm] = useState({ email: "", password: "", totp_secret: "", proxy_url: "", bearer_token: "", flow_project_url: "" });
  const [addLoading, setAddLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<Record<number, string>>({});
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<"accounts" | "users" | "plans" | "credits">("accounts");
  const [creditSettings, setCreditSettings] = useState({ videoCost: 1, imageCost: 1 });
  const [creditSaving, setCreditSaving] = useState(false);
  const [editAccount, setEditAccount] = useState<Account | null>(null);
  const [editForm, setEditForm] = useState({ password: "", totp_secret: "", proxy_url: "", flow_project_url: "" });
  const [editLoading, setEditLoading] = useState(false);
  const [selectedUser, setSelectedUser] = useState<any | null>(null);

  // Check if admin was previously authed in this session
  useEffect(() => {
    const savedToken = sessionStorage.getItem("admin_token");
    if (savedToken) setAuthed(true);
  }, []);

  const handleAdminAuth = async () => {
    setAuthLoading(true);
    setAuthError("");
    try {
      // Store key first so adminApi.authenticate can use it
      sessionStorage.setItem("admin_token", secretInput);
      await adminApi.authenticate(secretInput);
      setAuthed(true);
    } catch (e: any) {
      sessionStorage.removeItem("admin_token");
      setAuthError("Secret key không hợp lệ");
    } finally {
      setAuthLoading(false);
    }
  };

  const fetchStats = useCallback(async () => {
    try {
      setLoading(true);
      const data = await adminApi.getPool();
      setStats(data as PoolStats);
    } catch (e: any) {
      console.error("Admin pool error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authed) { fetchStats(); }
  }, [authed, fetchStats]);

  // Auto-refresh every 30s
  useEffect(() => {
    if (!authed) return;
    const interval = setInterval(fetchStats, 30000);
    return () => clearInterval(interval);
  }, [authed, fetchStats]);

  const totalVideos = stats?.accounts?.reduce((sum, a) => sum + a.usage_count, 0) ?? 0;

  // Secret Key Auth Gate
  if (!authed) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4" style={{ background: "var(--bg-primary)" }}>
        <div style={{ width: "100%", maxWidth: 400, margin: "0 auto" }}>
          <div className="text-center mb-8">
            <img src="/logo.png" alt="Veo3Lab" className="mx-auto mb-4 object-contain rounded-xl" style={{ height: 56, maxWidth: 120, boxShadow: "0 4px 20px rgba(0,0,0,0.3)" }} />
            <h1 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>Admin Panel</h1>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Nhập Secret Key để truy cập</p>
          </div>
          <div style={{ background: "var(--bg-elevated)", borderRadius: 16, padding: 24, border: "1px solid var(--border-subtle)", boxShadow: "0 4px 24px rgba(0,0,0,0.08)" }}>
            <input type="password" value={secretInput} onChange={e => setSecretInput(e.target.value)}
              className="input-field mb-4" placeholder="Secret Key..." autoFocus
              style={{ width: "100%", boxSizing: "border-box" }}
              onKeyDown={e => e.key === "Enter" && handleAdminAuth()} />
            {authError && (
              <p className="text-xs mb-3 flex items-center gap-1" style={{ color: "var(--error)" }}>
                <span className="material-symbols-rounded text-sm">error</span> {authError}
              </p>
            )}
            <button onClick={handleAdminAuth} disabled={authLoading || !secretInput}
              className="btn-generate flex items-center justify-center gap-2"
              style={{ width: "100%" }}>
              {authLoading ? <span className="spinner !w-4 !h-4 !border-white/20 !border-t-white"></span> : <span className="material-symbols-rounded text-lg">lock_open</span>}
              Xác thực
            </button>
          </div>
        </div>
      </div>
    );
  }

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddLoading(true);
    try {
      await adminApi.addAccount(addForm);
      showToast("Account added!", "success");
      setAddForm({ email: "", password: "", totp_secret: "", proxy_url: "", bearer_token: "", flow_project_url: "" });
      setAddOpen(false);
      fetchStats();
    } catch (e: any) {
      showToast(e.message || "Failed", "error");
    } finally {
      setAddLoading(false);
    }
  };

  const handleAction = async (id: number, action: "check" | "reset" | "delete") => {
    setActionLoading((prev) => ({ ...prev, [id]: action }));
    try {
      if (action === "check") {
        const res = await adminApi.healthCheck(id);
        showToast(res.message || "Check done", res.healthy ? "success" : "error");
      } else if (action === "reset") {
        await adminApi.resetAccount(id);
        showToast("Account reset", "success");
      } else if (action === "delete") {
        await adminApi.deleteAccount(id);
        showToast("Account deleted", "success");
      }
      fetchStats();
    } catch (e: any) {
      showToast(e.message || "Failed", "error");
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[id]; return n; });
    }
  };

  const handleToggle = async (id: number, email: string) => {
    setActionLoading((prev) => ({ ...prev, [id]: "toggle" }));
    try {
      const res = await adminApi.toggleAccount(id);
      showToast(res.message || "Toggled", "success");
      fetchStats();
    } catch (e: any) {
      showToast(e.message || "Failed", "error");
    } finally {
      setActionLoading((prev) => { const n = { ...prev }; delete n[id]; return n; });
    }
  };

  const handleEdit = (acc: Account) => {
    setEditAccount(acc);
    setEditForm({ password: "", totp_secret: "", proxy_url: acc.proxy_url || "", flow_project_url: acc.flow_project_url || "" });
  };

  const handleEditSave = async () => {
    if (!editAccount) return;
    setEditLoading(true);
    try {
      const payload: Record<string, string> = {};
      if (editForm.password) payload.password = editForm.password;
      if (editForm.totp_secret) payload.totp_secret = editForm.totp_secret;
      payload.proxy_url = editForm.proxy_url;
      payload.flow_project_url = editForm.flow_project_url || "";
      await adminApi.updateAccount(editAccount.id, payload);
      showToast("Account updated!", "success");
      setEditAccount(null);
      fetchStats();
    } catch (e: any) {
      showToast(e.message || "Failed", "error");
    } finally {
      setEditLoading(false);
    }
  };

  const statusBadge = (status: string) => {
    const map: Record<string, { cls: string; icon: string }> = {
      healthy: { cls: "badge-success", icon: "check_circle" },
      expired: { cls: "badge-warning", icon: "schedule" },
      banned: { cls: "badge-error", icon: "block" },
      cooldown: { cls: "badge-warning", icon: "hourglass_top" },
      error: { cls: "badge-error", icon: "error" },
    };
    const m = map[status] || map.error;
    return (
      <span className={`badge ${m.cls}`}>
        <span className="material-symbols-rounded text-xs">{m.icon}</span>
        {status}
      </span>
    );
  };

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Toast />

      {/* Stats Modal */}
      {selectedAccountId && (
        <StatsModal accountId={selectedAccountId} onClose={() => setSelectedAccountId(null)} />
      )}

      {/* ═══ SIDEBAR ═══ */}
      <aside className="fixed left-0 top-0 bottom-0 flex flex-col z-50 overflow-y-auto"
        style={{ width: 240, background: "var(--bg-elevated)", borderRight: "1px solid var(--border-subtle)", boxShadow: "2px 0 8px rgba(0,0,0,0.04)" }}>

        {/* Logo + Title */}
        <div className="flex items-center gap-3" style={{ padding: "28px 20px 20px 20px", borderBottom: "1px solid var(--border-subtle)" }}>
          <img src="/logo.png" alt="Veo3Lab" className="h-8 w-auto object-contain shrink-0 rounded-lg" />
          <div>
            <p className="text-sm font-bold leading-tight">
              <span className="gradient-text">Veo3Lab</span>{" "}
              <span style={{ color: "var(--text-primary)" }}>Admin</span>
            </p>
            <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>Admin Panel</p>
          </div>
        </div>

        {/* Nav Sections */}
        <nav className="flex-1 overflow-y-auto" style={{ padding: "28px 16px 24px 16px" }}>
          <p style={{ fontSize: 10, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.1em", padding: "0 12px", marginBottom: 20, color: "var(--text-muted)" }}>Quản lý</p>
          {([
            { key: "accounts" as const, label: "Accounts", icon: "group", badge: stats?.total_accounts },
            { key: "users" as const, label: "Người dùng", icon: "person", badge: 0 },
            { key: "plans" as const, label: "Gói đăng ký", icon: "card_membership", badge: null },
            { key: "credits" as const, label: "Cài đặt Credit", icon: "toll", badge: null },
          ] as const).map(item => (
            <button key={item.key} onClick={() => setActiveTab(item.key)}
              className="flex items-center gap-3 w-full rounded-lg text-[13px] font-medium transition-all"
              style={{
                padding: "14px 16px",
                marginBottom: 8,
                background: activeTab === item.key ? "var(--neon-blue)" : "transparent",
                color: activeTab === item.key ? "white" : "var(--text-secondary)",
              }}
              onMouseEnter={e => { if (activeTab !== item.key) e.currentTarget.style.background = "var(--bg-hover)"; }}
              onMouseLeave={e => { if (activeTab !== item.key) e.currentTarget.style.background = "transparent"; }}>
              <span className="material-symbols-rounded text-lg">{item.icon}</span>
              <span className="flex-1 text-left">{item.label}</span>
              {item.badge != null && (
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{
                  background: activeTab === item.key ? "rgba(255,255,255,0.25)" : "var(--bg-tertiary)",
                  color: activeTab === item.key ? "white" : "var(--text-muted)",
                }}>{item.badge}</span>
              )}
            </button>
          ))}
        </nav>

        {/* Bottom — Logout */}
        <div className="px-3 py-4" style={{ borderTop: "1px solid var(--border-subtle)" }}>
          <button onClick={() => { sessionStorage.removeItem("admin_token"); window.location.reload(); }}
            className="flex items-center gap-3 w-full px-3 py-2 rounded-lg text-[13px] font-medium transition-all"
            style={{ color: "var(--error)" }}
            onMouseEnter={e => e.currentTarget.style.background = "var(--bg-hover)"}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
            <span className="material-symbols-rounded text-lg">logout</span>
            Đăng xuất Admin
          </button>
        </div>
      </aside>

      {/* ═══ MAIN CONTENT ═══ */}
      <main style={{ marginLeft: 240, padding: "32px 40px 48px 40px" }} className="min-h-screen">

        {/* Header */}
        <div className="mb-8">
          <h1 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
            {activeTab === "accounts" ? "Quản lý Accounts" : activeTab === "users" ? "Quản lý Người dùng" : activeTab === "credits" ? "Cài đặt Credit" : "Gói đăng ký"}
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
            {activeTab === "accounts" ? "Theo dõi hoạt động, kiểm soát token & health" : activeTab === "users" ? "Quản lý người dùng đăng ký" : activeTab === "credits" ? "Chỉnh số credit tốn cho mỗi lần tạo video/ảnh" : "Quản lý các gói dịch vụ"}
          </p>
        </div>

        {/* ═══ Edit Account Modal ═══ */}
        {editAccount && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4"
            style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
            onClick={() => setEditAccount(null)}>
            <div className="w-full max-w-md rounded-xl p-6" onClick={e => e.stopPropagation()}
              style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", boxShadow: "0 8px 32px rgba(0,0,0,0.4)" }}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
                  <span className="material-symbols-rounded text-lg" style={{ color: "var(--neon-blue)" }}>edit</span>
                  Sửa: {editAccount.email}
                </h3>
                <button onClick={() => setEditAccount(null)} className="btn-ghost !p-1.5 !rounded-full">
                  <span className="material-symbols-rounded text-lg" style={{ color: "var(--text-muted)" }}>close</span>
                </button>
              </div>
              <div className="space-y-3">
                <div>
                  <label className="text-xs font-semibold block mb-1" style={{ color: "var(--text-secondary)" }}>Password mới (để trống = giữ nguyên)</label>
                  <input value={editForm.password} onChange={e => setEditForm({ ...editForm, password: e.target.value })}
                    className="input-field" type="password" placeholder="••••••••" />
                </div>
                <div>
                  <label className="text-xs font-semibold block mb-1" style={{ color: "var(--text-secondary)" }}>TOTP Secret (để trống = giữ nguyên)</label>
                  <input value={editForm.totp_secret} onChange={e => setEditForm({ ...editForm, totp_secret: e.target.value })}
                    className="input-field" placeholder="JBSWY3DPEHPK3PXP..." />
                </div>
                <div>
                  <label className="text-xs font-semibold block mb-1" style={{ color: "var(--text-secondary)" }}>Proxy URL</label>
                  <input value={editForm.proxy_url} onChange={e => setEditForm({ ...editForm, proxy_url: e.target.value })}
                    className="input-field" placeholder="http://user:pass@ip:port" />
                </div>
                <div>
                  <label className="text-xs font-semibold block mb-1" style={{ color: "var(--text-secondary)" }}>Flow Project URL <span style={{ color: "var(--neon-blue)" }}>(quan trọng cho upscale)</span></label>
                  <input value={editForm.flow_project_url || ""} onChange={e => setEditForm({ ...editForm, flow_project_url: e.target.value })}
                    className="input-field" placeholder="https://flow.nanoai.pics/project/xxxxxxxx" />
                </div>
              </div>
              <div className="flex justify-end gap-3 mt-5">
                <button onClick={() => setEditAccount(null)} className="btn-ghost">Hủy</button>
                <button onClick={handleEditSave} disabled={editLoading} className="btn-generate !py-2.5 !px-6 flex items-center gap-2">
                  {editLoading ? <span className="spinner !w-4 !h-4"></span> : <span className="material-symbols-rounded text-base">save</span>}
                  Lưu
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ═══ TAB: Accounts ═══ */}
        {activeTab === "accounts" && (
          <>
            {/* Stats Cards */}
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
              {[
                { label: "Tổng Accounts", value: stats?.total_accounts ?? 0, icon: "group", color: "var(--neon-blue)" },
                { label: "Healthy", value: stats?.healthy_accounts ?? 0, icon: "verified", color: "var(--success)" },
                { label: "Có Token", value: stats?.accounts?.filter(a => a.has_token).length ?? 0, icon: "key", color: "var(--neon-cyan)" },
                { label: "Chưa Token", value: stats?.accounts?.filter(a => !a.has_token).length ?? 0, icon: "key_off", color: "var(--error)" },
              ].map((s, i) => (
                <div key={i} className="glass-card p-5 flex items-center gap-4" style={{ boxShadow: "var(--shadow-card)" }}>
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center"
                    style={{ background: `${s.color}15` }}>
                    <span className="material-symbols-rounded text-xl" style={{ color: s.color }}>{s.icon}</span>
                  </div>
                  <div>
                    <p className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>{s.value}</p>
                    <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>{s.label}</p>
                  </div>
                </div>
              ))}
            </div>

            {/* Add Account Form */}
            <div className="flex justify-end mb-6">
              <button onClick={() => setAddOpen(!addOpen)} className="btn-generate !py-2.5 !px-5 flex items-center gap-2 text-sm">
                <span className="material-symbols-rounded text-base">add</span>
                Thêm Account
              </button>
            </div>

            {addOpen && (
              <div className="glass-card p-6 mb-6 fade-in" style={{ boxShadow: "var(--shadow-card)" }}>
                <h3 className="text-sm font-semibold mb-4 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
                  <span className="material-symbols-rounded text-lg" style={{ color: "var(--neon-blue)" }}>person_add</span>
                  Thêm Account
                </h3>
                <form onSubmit={handleAdd} className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <input value={addForm.email} onChange={(e) => setAddForm({ ...addForm, email: e.target.value })}
                    className="input-field" placeholder="Email" required type="email" />
                  <input value={addForm.password} onChange={(e) => setAddForm({ ...addForm, password: e.target.value })}
                    className="input-field" placeholder="Password" required type="password" />
                  <input value={addForm.totp_secret} onChange={(e) => setAddForm({ ...addForm, totp_secret: e.target.value })}
                    className="input-field" placeholder="TOTP Secret / 2FA Key" />
                  <input value={addForm.proxy_url} onChange={(e) => setAddForm({ ...addForm, proxy_url: e.target.value })}
                    className="input-field" placeholder="Proxy URL (tùy chọn)" />
                  <input value={addForm.bearer_token} onChange={(e) => setAddForm({ ...addForm, bearer_token: e.target.value })}
                    className="input-field" placeholder="Bearer Token (tùy chọn)" />
                  <input value={addForm.flow_project_url} onChange={(e) => setAddForm({ ...addForm, flow_project_url: e.target.value })}
                    className="input-field" placeholder="Flow Project URL (tùy chọn)" />
                  <div className="md:col-span-3 flex justify-end">
                    <button type="button" onClick={() => setAddOpen(false)} className="btn-ghost mr-3">Hủy</button>
                    <button type="submit" disabled={addLoading} className="btn-generate !py-2.5 !px-6 flex items-center gap-2">
                      {addLoading ? <span className="spinner !w-4 !h-4"></span> : <span className="material-symbols-rounded text-base">add</span>}
                      Thêm
                    </button>
                  </div>
                </form>
              </div>
            )}

            {/* Accounts Table */}
            <div className="glass-card overflow-hidden" style={{ boxShadow: "var(--shadow-card)", marginTop: 8 }}>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                      {["Email", "Trạng thái", "Health", "Token", "Cookie", "Concurrent", "Proxy", "Lần dùng cuối", "Thao tác"].map((h) => (
                        <th key={h} className="text-left px-5 py-4 text-xs font-semibold uppercase tracking-wider"
                          style={{ color: "var(--text-muted)" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {loading ? (
                      <tr><td colSpan={9} className="text-center py-12">
                        <div className="spinner spinner-lg mx-auto"></div>
                      </td></tr>
                    ) : !stats?.accounts?.length ? (
                      <tr><td colSpan={9} className="text-center py-12" style={{ color: "var(--text-muted)" }}>
                        <span className="material-symbols-rounded text-4xl block mb-2">cloud_off</span>
                        Chưa có account nào
                      </td></tr>
                    ) : (
                      stats.accounts.map((acc) => (
                        <tr key={acc.id} className="transition-colors cursor-pointer"
                          style={{ borderBottom: "1px solid var(--border-subtle)", opacity: acc.is_enabled ? 1 : 0.4 }}
                          onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg-hover)"}
                          onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                          onClick={() => setSelectedAccountId(acc.id)}>
                          <td className="px-5 py-4">
                            <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{acc.email}</span>
                          </td>
                          <td className="px-5 py-4">
                            <div className="flex items-center gap-2">
                              <button
                                onClick={(e) => { e.stopPropagation(); handleToggle(acc.id, acc.email); }}
                                disabled={actionLoading[acc.id] === "toggle"}
                                className="relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 focus:outline-none flex-shrink-0"
                                style={{ background: acc.is_enabled ? "var(--success)" : "var(--bg-tertiary)" }}
                                title={acc.is_enabled ? "Đang BẬT — click để tắt" : "Đang TẮT — click để bật"}
                              >
                                <span className="inline-block h-3.5 w-3.5 rounded-full bg-white shadow-sm transform transition-transform duration-200"
                                  style={{ transform: acc.is_enabled ? "translateX(18px)" : "translateX(3px)" }} />
                              </button>
                              {statusBadge(acc.status)}
                            </div>
                          </td>
                          <td className="px-5 py-4">
                            <div className="flex items-center gap-2">
                              <div className="w-14 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-tertiary)" }}>
                                <div className="h-full rounded-full" style={{
                                  width: `${acc.health_score}%`,
                                  background: acc.health_score > 70 ? "var(--success)" : acc.health_score > 40 ? "var(--warning)" : "var(--error)",
                                }} />
                              </div>
                              <span className="text-xs" style={{ color: "var(--text-muted)" }}>{acc.health_score}%</span>
                            </div>
                          </td>
                          <td className="px-5 py-4">
                            {acc.has_token ? (() => {
                              return (
                                <div className="flex flex-col gap-0.5">
                                  <div className="flex items-center gap-1.5">
                                    <span className="w-2 h-2 rounded-full" style={{ background: "var(--success)" }}></span>
                                    <span className="text-xs font-mono cursor-pointer hover:opacity-80"
                                      style={{ color: "var(--success)" }}
                                      title="Click để copy token"
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        if (acc.bearer_token) {
                                          navigator.clipboard.writeText(acc.bearer_token);
                                          showToast('Đã copy token!', 'success');
                                        }
                                      }}>
                                      {acc.bearer_token ? `ya29...${acc.bearer_token.slice(-8)}` : 'Có token'}
                                    </span>
                                  </div>
                                  {acc.token_expires_at && <CountdownTimer expiresAt={acc.token_expires_at} />}
                                </div>
                              );
                            })() : (
                              <span className="flex items-center gap-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
                                <span className="w-2 h-2 rounded-full" style={{ background: 'var(--error)' }}></span>
                                Chưa có
                              </span>
                            )}
                          </td>
                          <td className="px-5 py-4">
                            {acc.cookies ? (
                              <span className="flex items-center gap-1.5 text-xs cursor-pointer hover:opacity-80"
                                style={{ color: "var(--success)" }}
                                title="Click để copy cookie"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  navigator.clipboard.writeText(acc.cookies!);
                                  showToast('Đã copy cookie!', 'success');
                                }}>
                                <span className="w-2 h-2 rounded-full" style={{ background: "var(--success)" }}></span>
                                {acc.cookies.length} chars
                              </span>
                            ) : (
                              <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--text-muted)" }}>
                                <span className="w-2 h-2 rounded-full" style={{ background: "var(--error)" }}></span>
                                Chưa có
                              </span>
                            )}
                          </td>
                          <td className="px-5 py-4 text-sm" style={{ color: "var(--text-secondary)" }}>
                            {acc.current_concurrent}/{acc.max_concurrent}
                          </td>
                          <td className="px-5 py-4 text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                            {acc.proxy_url ? acc.proxy_url.substring(0, 20) + "..." : "-"}
                          </td>
                          <td className="px-5 py-4 text-xs" style={{ color: "var(--text-muted)" }}>
                            {acc.last_used_at ? new Date(acc.last_used_at).toLocaleString("vi-VN") : "-"}
                          </td>
                          <td className="px-5 py-4" onClick={e => e.stopPropagation()}>
                            <div className="flex items-center gap-1">
                              <button onClick={() => handleEdit(acc)}
                                className="btn-ghost !p-1.5 !rounded-lg" title="Sửa">
                                <span className="material-symbols-rounded text-base" style={{ color: "var(--neon-blue)" }}>edit</span>
                              </button>
                              <button onClick={() => handleAction(acc.id, "check")} disabled={!!actionLoading[acc.id]}
                                className="btn-ghost !p-1.5 !rounded-lg" title="Health Check">
                                {actionLoading[acc.id] === "check"
                                  ? <span className="spinner !w-4 !h-4"></span>
                                  : <span className="material-symbols-rounded text-base" style={{ color: "var(--neon-cyan)" }}>monitor_heart</span>}
                              </button>
                              <button onClick={() => handleAction(acc.id, "reset")} disabled={!!actionLoading[acc.id]}
                                className="btn-ghost !p-1.5 !rounded-lg" title="Reset">
                                {actionLoading[acc.id] === "reset"
                                  ? <span className="spinner !w-4 !h-4"></span>
                                  : <span className="material-symbols-rounded text-base" style={{ color: "var(--warning)" }}>restart_alt</span>}
                              </button>
                              <button onClick={() => { if (confirm(`Xóa ${acc.email}?`)) handleAction(acc.id, "delete"); }}
                                disabled={!!actionLoading[acc.id]}
                                className="btn-ghost !p-1.5 !rounded-lg" title="Xóa">
                                {actionLoading[acc.id] === "delete"
                                  ? <span className="spinner !w-4 !h-4"></span>
                                  : <span className="material-symbols-rounded text-base" style={{ color: "var(--error)" }}>delete</span>}
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}

        {/* ═══ TAB: Users ═══ */}
        {activeTab === "users" && <UsersTab />}

        {/* ═══ TAB: Gói đăng ký ═══ */}
        {activeTab === "plans" && <PlansTab />}

        {/* ═══ CREDITS TAB ═══ */}
        {activeTab === "credits" && (
          <div className="max-w-2xl">
            <div className="rounded-xl p-6 mb-6" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", boxShadow: "0 2px 12px rgba(0,0,0,0.06)" }}>
              <h3 className="text-sm font-bold mb-5 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
                <span className="material-symbols-rounded text-lg" style={{ color: "var(--neon-purple)" }}>toll</span>
                Chi phí Credit cho mỗi lần tạo
              </h3>

              <div className="space-y-5">
                {/* Video credit cost */}
                <div className="rounded-lg p-4" style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border-subtle)" }}>
                  <div className="flex items-center gap-3 mb-3">
                    <span className="material-symbols-rounded text-2xl" style={{ color: "var(--neon-blue)" }}>videocam</span>
                    <div>
                      <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Tạo Video</p>
                      <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>Số credit trừ mỗi lần tạo 1 video</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <input
                      type="number" min={0} step={1}
                      value={creditSettings.videoCost}
                      onChange={e => setCreditSettings(prev => ({ ...prev, videoCost: Number(e.target.value) }))}
                      className="input-field !py-2 !text-lg font-bold text-center"
                      style={{ width: 120, background: "var(--bg-input)" }}
                    />
                    <span className="text-sm font-medium" style={{ color: "var(--text-muted)" }}>credits / video</span>
                  </div>
                </div>

                {/* Image credit cost */}
                <div className="rounded-lg p-4" style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border-subtle)" }}>
                  <div className="flex items-center gap-3 mb-3">
                    <span className="material-symbols-rounded text-2xl" style={{ color: "var(--neon-purple)" }}>image</span>
                    <div>
                      <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Tạo Ảnh</p>
                      <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>Số credit trừ mỗi lần tạo 1 ảnh</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <input
                      type="number" min={0} step={1}
                      value={creditSettings.imageCost}
                      onChange={e => setCreditSettings(prev => ({ ...prev, imageCost: Number(e.target.value) }))}
                      className="input-field !py-2 !text-lg font-bold text-center"
                      style={{ width: 120, background: "var(--bg-input)" }}
                    />
                    <span className="text-sm font-medium" style={{ color: "var(--text-muted)" }}>credits / ảnh</span>
                  </div>
                </div>
              </div>

              {/* Save button */}
              <div className="flex justify-end mt-6">
                <button
                  onClick={() => {
                    setCreditSaving(true);
                    localStorage.setItem('veo3_credit_settings', JSON.stringify(creditSettings));
                    setTimeout(() => {
                      setCreditSaving(false);
                      showToast('✅ Đã lưu cài đặt credit!', 'success');
                    }, 500);
                  }}
                  disabled={creditSaving}
                  className="btn-generate !py-2.5 !px-6 flex items-center gap-2 text-sm"
                >
                  {creditSaving ? <span className="spinner !w-4 !h-4 !border-white/20 !border-t-white"></span> : <span className="material-symbols-rounded text-base">save</span>}
                  Lưu cài đặt
                </button>
              </div>
            </div>

            {/* Info card */}
            <div className="rounded-xl p-5" style={{ background: "linear-gradient(135deg, rgba(99,102,241,0.08), rgba(168,85,247,0.08))", border: "1px solid rgba(99,102,241,0.2)" }}>
              <div className="flex items-start gap-3">
                <span className="material-symbols-rounded text-xl" style={{ color: "var(--neon-blue)" }}>info</span>
                <div>
                  <p className="text-sm font-semibold mb-1" style={{ color: "var(--text-primary)" }}>Hướng dẫn</p>
                  <ul className="text-xs space-y-1" style={{ color: "var(--text-secondary)" }}>
                    <li>• Số credit sẽ được trừ từ tài khoản user mỗi khi tạo video/ảnh</li>
                    <li>• Đặt = 0 nghĩa là miễn phí (không trừ credit)</li>
                    <li>• User cần nạp credit qua các Gói đăng ký trước khi sử dụng</li>
                    <li>• Cài đặt sẽ áp dụng cho tất cả user</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════════
 * UsersTab — Full user management with detail modal
 * ═══════════════════════════════════════════════════════════════════════════════ */
function UsersTab() {
  const showToast = useStore((s) => s.showToast);
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedUser, setSelectedUser] = useState<any | null>(null);
  const [balanceAmount, setBalanceAmount] = useState("");
  const [balanceReason, setBalanceReason] = useState("Admin nạp tiền");
  const [userJobs, setUserJobs] = useState<any[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);

  const fetchUsers = useCallback(async () => {
    try {
      setLoading(true);
      const data = await adminApi.getUsers(200);
      setUsers(data.users || []);
    } catch { } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  const filtered = users.filter(u =>
    u.username.toLowerCase().includes(search.toLowerCase()) ||
    (u.email || "").toLowerCase().includes(search.toLowerCase())
  );

  const openUserDetail = async (u: any) => {
    setSelectedUser(u);
    setBalanceAmount("");
    setBalanceReason("Admin nạp tiền");
    // Fetch user's jobs for stats
    setJobsLoading(true);
    try {
      const data = await adminApi.getLogs("jobs", 200);
      const uJobs = (data.logs || []).filter((j: any) => j.user_id === u.id);
      setUserJobs(uJobs);
    } catch { setUserJobs([]); }
    finally { setJobsLoading(false); }
  };

  const handleBan = async (userId: number) => {
    try {
      const res = await adminApi.toggleBanUser(userId);
      showToast(res.is_banned ? "🚫 Đã khóa user" : "✅ Đã mở khóa user", "success");
      fetchUsers();
      if (selectedUser?.id === userId) {
        setSelectedUser({ ...selectedUser, is_banned: res.is_banned });
      }
    } catch (e: any) { showToast(e.message, "error"); }
  };

  const handleBalance = async () => {
    if (!selectedUser || !balanceAmount) return;
    try {
      await adminApi.adjustBalance(selectedUser.id, parseInt(balanceAmount), balanceReason);
      showToast(`✅ Đã cập nhật số dư`, "success");
      setBalanceAmount("");
      fetchUsers();
      // Update selected user balance locally
      const newBal = selectedUser.balance + parseInt(balanceAmount);
      setSelectedUser({ ...selectedUser, balance: newBal });
    } catch (e: any) { showToast(e.message, "error"); }
  };

  const handleRole = async (userId: number, currentRole: string) => {
    const newRole = currentRole === "admin" ? "customer" : "admin";
    if (!confirm(`Chuyển user thành ${newRole}?`)) return;
    try {
      await adminApi.updateUserRole(userId, newRole);
      showToast(`✅ Đã đổi role → ${newRole}`, "success");
      fetchUsers();
      if (selectedUser?.id === userId) setSelectedUser({ ...selectedUser, role: newRole });
    } catch (e: any) { showToast(e.message, "error"); }
  };

  const completedJobs = userJobs.filter(j => j.status === "completed").length;
  const failedJobs = userJobs.filter(j => j.status === "failed").length;

  return (
    <>
      {/* ══════ User Detail Modal ══════ */}
      {selectedUser && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)" }}
          onClick={() => setSelectedUser(null)}>
          <div className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl" onClick={e => e.stopPropagation()}
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", boxShadow: "var(--shadow-dropdown)" }}>

            {/* Header */}
            <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 rounded-t-2xl"
              style={{ background: "var(--bg-elevated)", borderBottom: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold"
                  style={{ background: "var(--gradient-neon)", color: "white" }}>
                  {selectedUser.username[0].toUpperCase()}
                </div>
                <div>
                  <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>{selectedUser.username}</h3>
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>{selectedUser.email || "Chưa có email"}</p>
                </div>
              </div>
              <button onClick={() => setSelectedUser(null)} className="btn-ghost !p-1.5">
                <span className="material-symbols-rounded text-lg" style={{ color: "var(--text-muted)" }}>close</span>
              </button>
            </div>

            <div className="p-6 space-y-6">
              {/* Info Cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: "Số dư", value: `${selectedUser.balance?.toLocaleString()} credits`, icon: "account_balance_wallet", color: "var(--neon-blue)" },
                  { label: "Tổng nạp", value: `${(selectedUser.total_deposit || 0).toLocaleString()} credits`, icon: "savings", color: "var(--neon-purple)" },
                  { label: "Video tạo", value: `${userJobs.length}`, icon: "movie", color: "var(--neon-cyan)" },
                  { label: "Thành công", value: `${completedJobs}`, icon: "check_circle", color: "var(--success)" },
                ].map(c => (
                  <div key={c.label} className="rounded-xl p-3 text-center" style={{ background: "var(--bg-tertiary)" }}>
                    <span className="material-symbols-rounded text-lg block mb-1" style={{ color: c.color }}>{c.icon}</span>
                    <p className="text-base font-bold" style={{ color: c.color }}>{c.value}</p>
                    <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>{c.label}</p>
                  </div>
                ))}
              </div>

              {/* Details Grid */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-[10px] font-semibold block mb-1" style={{ color: "var(--text-muted)" }}>Role</label>
                  <button onClick={() => handleRole(selectedUser.id, selectedUser.role)}
                    className={`badge ${selectedUser.role === "admin" ? "badge-neon" : ""} cursor-pointer`}
                    title="Click để đổi role">{selectedUser.role}</button>
                </div>
                <div>
                  <label className="text-[10px] font-semibold block mb-1" style={{ color: "var(--text-muted)" }}>Trạng thái</label>
                  <span className={`badge ${selectedUser.is_banned ? "badge-error" : "badge-success"}`}>
                    {selectedUser.is_banned ? "Đã khóa" : "Active"}
                  </span>
                </div>
                <div>
                  <label className="text-[10px] font-semibold block mb-1" style={{ color: "var(--text-muted)" }}>Ngày tạo</label>
                  <p className="text-xs" style={{ color: "var(--text-primary)" }}>
                    {selectedUser.created_at ? new Date(selectedUser.created_at).toLocaleString("vi-VN") : "-"}
                  </p>
                </div>
                <div>
                  <label className="text-[10px] font-semibold block mb-1" style={{ color: "var(--text-muted)" }}>Gói đăng ký</label>
                  <p className="text-xs" style={{ color: "var(--text-primary)" }}>
                    {selectedUser.plan_id ? `Plan #${selectedUser.plan_id}` : "Chưa có gói"}
                    {selectedUser.plan_expires_at && <span className="ml-1" style={{ color: "var(--text-muted)" }}>→ {new Date(selectedUser.plan_expires_at).toLocaleDateString("vi-VN")}</span>}
                  </p>
                </div>
              </div>

              {/* API Key */}
              <div>
                <label className="text-[10px] font-semibold block mb-1" style={{ color: "var(--text-muted)" }}>API Key</label>
                <div className="rounded-lg px-3 py-2 flex items-center justify-between" style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border-subtle)" }}>
                  <code className="text-xs font-mono" style={{ color: "var(--neon-blue)" }}>
                    {selectedUser.api_key || "Chưa tạo API key"}
                  </code>
                  {selectedUser.api_key && (
                    <button onClick={() => { navigator.clipboard.writeText(selectedUser.api_key); showToast("📋 Đã copy API key", "success"); }}
                      className="btn-ghost !p-1" title="Copy">
                      <span className="material-symbols-rounded text-sm" style={{ color: "var(--text-muted)" }}>content_copy</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Balance Adjustment */}
              <div className="rounded-xl p-4" style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border-subtle)" }}>
                <h4 className="text-xs font-bold mb-3 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
                  <span className="material-symbols-rounded text-sm" style={{ color: "var(--neon-blue)" }}>payments</span>
                  Nạp / Trừ tiền
                </h4>
                <div className="flex gap-2">
                  <input type="number" value={balanceAmount} onChange={e => setBalanceAmount(e.target.value)}
                    className="input-field flex-1" placeholder="Số tiền (VD: 50000)" />
                  <input type="text" value={balanceReason} onChange={e => setBalanceReason(e.target.value)}
                    className="input-field flex-1" placeholder="Lý do" />
                  <button onClick={handleBalance} disabled={!balanceAmount}
                    className="btn-generate !py-2 !px-4 shrink-0">Xác nhận</button>
                </div>
              </div>

              {/* Actions */}
              <div className="flex gap-3">
                <button onClick={() => handleBan(selectedUser.id)}
                  className={`flex-1 py-2.5 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-all ${selectedUser.is_banned ? 'btn-generate' : ''}`}
                  style={selectedUser.is_banned ? {} : { background: "var(--bg-tertiary)", color: "var(--error)", border: "1px solid var(--error)" }}>
                  <span className="material-symbols-rounded text-base">
                    {selectedUser.is_banned ? "lock_open" : "block"}
                  </span>
                  {selectedUser.is_banned ? "Mở khóa" : "Khóa tài khoản"}
                </button>
              </div>

              {/* Recent Jobs */}
              <div>
                <h4 className="text-xs font-bold mb-3 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
                  <span className="material-symbols-rounded text-sm" style={{ color: "var(--neon-cyan)" }}>history</span>
                  Lịch sử tạo gần đây ({userJobs.length} jobs — {completedJobs} ✓ / {failedJobs} ✗)
                </h4>
                {jobsLoading ? (
                  <div className="text-center py-4"><div className="spinner mx-auto"></div></div>
                ) : userJobs.length === 0 ? (
                  <p className="text-xs text-center py-4" style={{ color: "var(--text-muted)" }}>Chưa có job nào</p>
                ) : (
                  <div className="space-y-1.5 max-h-48 overflow-y-auto">
                    {userJobs.slice(0, 20).map((j: any) => (
                      <div key={j.id} className="flex items-center gap-3 px-3 py-2 rounded-lg text-xs"
                        style={{ background: "var(--bg-tertiary)" }}>
                        <span className={`badge ${j.status === "completed" ? "badge-success" : j.status === "failed" ? "badge-error" : "badge-neon"}`}>
                          {j.status}
                        </span>
                        <span className="flex-1 truncate" style={{ color: "var(--text-secondary)" }}>
                          {j.prompt}
                        </span>
                        <span style={{ color: "var(--text-muted)" }}>
                          {j.created_at ? new Date(j.created_at).toLocaleDateString("vi-VN") : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Search */}
      <div className="flex items-center gap-4 mb-6">
        <div className="relative flex-1 max-w-sm">
          <span className="material-symbols-rounded absolute left-3 top-1/2 -translate-y-1/2 text-lg" style={{ color: "var(--text-muted)" }}>search</span>
          <input value={search} onChange={e => setSearch(e.target.value)}
            className="input-field !pl-10" placeholder="Tìm user..." />
        </div>
        <span className="text-sm" style={{ color: "var(--text-muted)" }}>{filtered.length} users</span>
      </div>

      {/* Users Table */}
      <div className="glass-card overflow-hidden" style={{ boxShadow: "var(--shadow-card)" }}>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                {["ID", "Username", "Email", "Role", "Số dư", "API Key", "Trạng thái", "Ngày tạo"].map(h => (
                  <th key={h} className="text-left px-4 py-3 text-[11px] font-semibold uppercase tracking-wider"
                    style={{ color: "var(--text-muted)" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="text-center py-12"><div className="spinner spinner-lg mx-auto"></div></td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={8} className="text-center py-12" style={{ color: "var(--text-muted)" }}>Không tìm thấy user</td></tr>
              ) : filtered.map(u => (
                <tr key={u.id} className="transition-colors cursor-pointer"
                  style={{ borderBottom: "1px solid var(--border-subtle)", opacity: u.is_banned ? 0.5 : 1 }}
                  onClick={() => openUserDetail(u)}
                  onMouseEnter={e => e.currentTarget.style.background = "var(--bg-hover)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                  <td className="px-4 py-3 text-xs font-mono" style={{ color: "var(--text-muted)" }}>#{u.id}</td>
                  <td className="px-4 py-3 text-sm font-medium" style={{ color: "var(--neon-blue)" }}>{u.username}</td>
                  <td className="px-4 py-3 text-xs" style={{ color: "var(--text-muted)" }}>{u.email || "-"}</td>
                  <td className="px-4 py-3">
                    <span className={`badge ${u.role === "admin" ? "badge-neon" : ""}`}>{u.role}</span>
                  </td>
                  <td className="px-4 py-3 text-sm font-semibold" style={{ color: "var(--neon-blue)" }}>
                    {u.balance?.toLocaleString()} credits
                  </td>
                  <td className="px-4 py-3 text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                    {u.api_key ? `${u.api_key.slice(0, 10)}...` : "-"}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`badge ${u.is_banned ? "badge-error" : "badge-success"}`}>
                      {u.is_banned ? "Khóa" : "Active"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: "var(--text-muted)" }}>
                    {u.created_at ? new Date(u.created_at).toLocaleDateString("vi-VN") : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}


/* ═══════════════════════════════════════════════════════════════════════════════
 * PlansTab — Subscription plans CRUD
 * ═══════════════════════════════════════════════════════════════════════════════ */
function PlansTab() {
  const showToast = useStore((s) => s.showToast);
  const [plans, setPlans] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [editPlan, setEditPlan] = useState<any | null>(null); // null=closed, {}=new, {id:...}=editing
  const [form, setForm] = useState({ name: "", description: "", credits: "", price: "", duration_days: "30", max_concurrent: "4", sort_order: "0", is_active: true });
  const [saving, setSaving] = useState(false);

  const fetchPlans = useCallback(async () => {
    try {
      setLoading(true);
      const data = await adminApi.getPlans();
      setPlans(data.plans || []);
    } catch { } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchPlans(); }, [fetchPlans]);

  const openNew = () => {
    setForm({ name: "", description: "", credits: "", price: "", duration_days: "30", max_concurrent: "4", sort_order: "0", is_active: true });
    setEditPlan({});
  };

  const openEdit = (p: any) => {
    setForm({
      name: p.name, description: p.description || "", credits: String(p.credits),
      price: String(p.price), duration_days: String(p.duration_days),
      max_concurrent: String(p.max_concurrent), sort_order: String(p.sort_order || 0),
      is_active: p.is_active,
    });
    setEditPlan(p);
  };

  const handleSave = async () => {
    if (!form.name || !form.credits || !form.price) return showToast("Điền đầy đủ thông tin", "error");
    setSaving(true);
    try {
      const body = {
        name: form.name, description: form.description,
        credits: parseInt(form.credits), price: parseInt(form.price),
        duration_days: parseInt(form.duration_days), max_concurrent: parseInt(form.max_concurrent),
        sort_order: parseInt(form.sort_order), is_active: form.is_active,
      };
      if (editPlan?.id) {
        await adminApi.updatePlan(editPlan.id, body);
        showToast("✅ Đã cập nhật gói", "success");
      } else {
        await adminApi.createPlan(body);
        showToast("✅ Đã tạo gói mới", "success");
      }
      setEditPlan(null);
      fetchPlans();
    } catch (e: any) { showToast(e.message, "error"); }
    finally { setSaving(false); }
  };

  const handleDelete = async (planId: number, planName: string) => {
    if (!confirm(`Xóa gói "${planName}"?`)) return;
    try {
      await adminApi.deletePlan(planId);
      showToast("🗑️ Đã xóa", "success");
      fetchPlans();
    } catch (e: any) { showToast(e.message, "error"); }
  };

  return (
    <>
      {/* Edit/Create Modal */}
      {editPlan !== null && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
          onClick={() => setEditPlan(null)}>
          <div className="w-full max-w-md rounded-xl p-6" onClick={e => e.stopPropagation()}
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}>
            <h3 className="text-sm font-bold mb-4 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <span className="material-symbols-rounded text-lg" style={{ color: "var(--neon-purple)" }}>
                {editPlan?.id ? "edit" : "add_circle"}
              </span>
              {editPlan?.id ? "Sửa gói" : "Tạo gói mới"}
            </h3>
            <div className="space-y-3">
              <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                className="input-field" placeholder="Tên gói (VD: Pro, Enterprise)" autoFocus />
              <textarea value={form.description} onChange={e => setForm({ ...form, description: e.target.value })}
                className="input-field !h-20 resize-none" placeholder="Mô tả gói..." />
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-[10px] font-semibold block mb-1" style={{ color: "var(--text-muted)" }}>Credits</label>
                  <input type="number" value={form.credits} onChange={e => setForm({ ...form, credits: e.target.value })}
                    className="input-field" placeholder="100000" />
                </div>
                <div>
                  <label className="text-[10px] font-semibold block mb-1" style={{ color: "var(--text-muted)" }}>Giá (đ)</label>
                  <input type="number" value={form.price} onChange={e => setForm({ ...form, price: e.target.value })}
                    className="input-field" placeholder="200000" />
                </div>
                <div>
                  <label className="text-[10px] font-semibold block mb-1" style={{ color: "var(--text-muted)" }}>Thời hạn (ngày)</label>
                  <input type="number" value={form.duration_days} onChange={e => setForm({ ...form, duration_days: e.target.value })}
                    className="input-field" placeholder="30" />
                </div>
                <div>
                  <label className="text-[10px] font-semibold block mb-1" style={{ color: "var(--text-muted)" }}>Max concurrent</label>
                  <input type="number" value={form.max_concurrent} onChange={e => setForm({ ...form, max_concurrent: e.target.value })}
                    className="input-field" placeholder="4" />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <label className="flex items-center gap-2 cursor-pointer text-sm" style={{ color: "var(--text-secondary)" }}>
                  <input type="checkbox" checked={form.is_active} onChange={e => setForm({ ...form, is_active: e.target.checked })} />
                  Hiển thị gói
                </label>
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-5">
              <button onClick={() => setEditPlan(null)} className="btn-ghost">Hủy</button>
              <button onClick={handleSave} disabled={saving} className="btn-generate !py-2.5 !px-6 flex items-center gap-2">
                {saving ? <span className="spinner !w-4 !h-4"></span> : <span className="material-symbols-rounded text-base">save</span>}
                {editPlan?.id ? "Lưu" : "Tạo"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add button */}
      <div className="flex justify-end mb-6">
        <button onClick={openNew} className="btn-generate !py-2.5 !px-5 flex items-center gap-2 text-sm">
          <span className="material-symbols-rounded text-base">add</span>
          Thêm gói
        </button>
      </div>

      {/* Plans grid */}
      {loading ? (
        <div className="text-center py-12"><div className="spinner spinner-lg mx-auto"></div></div>
      ) : plans.length === 0 ? (
        <div className="glass-card p-8 text-center" style={{ boxShadow: "var(--shadow-card)" }}>
          <span className="material-symbols-rounded text-5xl block mb-4" style={{ color: "var(--neon-purple)" }}>card_membership</span>
          <h3 className="text-lg font-bold mb-2" style={{ color: "var(--text-primary)" }}>Chưa có gói nào</h3>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>Bấm "Thêm gói" để tạo gói đăng ký đầu tiên.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {plans.map(p => (
            <div key={p.id} className="glass-card p-5 relative" style={{ boxShadow: "var(--shadow-card)", opacity: p.is_active ? 1 : 0.5 }}>
              {!p.is_active && (
                <span className="absolute top-3 right-3 badge badge-warning">Ẩn</span>
              )}
              <h4 className="text-base font-bold mb-1" style={{ color: "var(--text-primary)" }}>{p.name}</h4>
              {p.description && <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>{p.description}</p>}

              <div className="grid grid-cols-2 gap-3 mb-4">
                <div className="rounded-lg p-2.5 text-center" style={{ background: "var(--bg-tertiary)" }}>
                  <p className="text-lg font-bold" style={{ color: "var(--neon-blue)" }}>{p.credits.toLocaleString()}</p>
                  <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>Credits</p>
                </div>
                <div className="rounded-lg p-2.5 text-center" style={{ background: "var(--bg-tertiary)" }}>
                  <p className="text-lg font-bold" style={{ color: "var(--neon-purple)" }}>{p.price.toLocaleString()} credits</p>
                  <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>Credits</p>
                </div>
              </div>

              <div className="flex items-center gap-3 text-xs mb-4" style={{ color: "var(--text-muted)" }}>
                <span className="flex items-center gap-1">
                  <span className="material-symbols-rounded text-sm">schedule</span>
                  {p.duration_days} ngày
                </span>
                <span className="flex items-center gap-1">
                  <span className="material-symbols-rounded text-sm">bolt</span>
                  Max {p.max_concurrent} concurrent
                </span>
              </div>

              <div className="flex items-center gap-2">
                <button onClick={() => openEdit(p)} className="btn-ghost !p-1.5 !rounded-lg" title="Sửa">
                  <span className="material-symbols-rounded text-base" style={{ color: "var(--neon-blue)" }}>edit</span>
                </button>
                <button onClick={() => handleDelete(p.id, p.name)} className="btn-ghost !p-1.5 !rounded-lg" title="Xóa">
                  <span className="material-symbols-rounded text-base" style={{ color: "var(--error)" }}>delete</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
