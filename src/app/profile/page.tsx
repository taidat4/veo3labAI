/**
 * Profile Page — User account management
 * Features: view stats, API key, change password, account info
 */
"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import { Navbar } from "@/components/Navbar";
import { Toast } from "@/components/Toast";

interface ProfileData {
  user_id: number;
  username: string;
  email: string;
  role: string;
  balance: number;
  is_banned: boolean;
  api_key: string | null;
  plan_id: number | null;
  plan_expires_at: string | null;
  created_at: string;
}

export default function ProfilePage() {
  const router = useRouter();
  const user = useStore((s) => s.user);
  const setUser = useStore((s) => s.setUser);
  const showToast = useStore((s) => s.showToast);
  const history = useStore((s) => s.history);
  const setHistory = useStore((s) => s.setHistory);

  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [loading, setLoading] = useState(true);

  // API Key
  const [showApiKey, setShowApiKey] = useState(false);
  const [generatingKey, setGeneratingKey] = useState(false);

  // Change password
  const [showPassForm, setShowPassForm] = useState(false);
  const [currentPass, setCurrentPass] = useState("");
  const [newPass, setNewPass] = useState("");
  const [confirmPass, setConfirmPass] = useState("");
  const [changingPass, setChangingPass] = useState(false);

  // Auth check
  useEffect(() => {
    const stored = localStorage.getItem("veo3_user");
    const token = localStorage.getItem("veo3_token");
    if (stored && token) {
      setUser({ ...JSON.parse(stored), token });
    } else {
      router.push("/login");
    }
  }, [router, setUser]);

  // Fetch profile + history
  const fetchProfile = useCallback(async () => {
    try {
      const [me, jobsData] = await Promise.all([
        api.getMe(),
        api.getJobs(200),
      ]);
      setProfile(me as ProfileData);
      setHistory(jobsData.jobs || []);
    } catch { } finally {
      setLoading(false);
    }
  }, [setHistory]);

  useEffect(() => {
    if (user) fetchProfile();
  }, [user, fetchProfile]);

  // Stats from history
  const totalJobs = history.length;
  const completedJobs = history.filter(j => j.status === "completed").length;
  const failedJobs = history.filter(j => j.status === "failed").length;
  const videoJobs = history.filter(j => (j.media_type || "video") === "video" && j.status === "completed").length;
  const imageJobs = history.filter(j => j.media_type === "image" && j.status === "completed").length;
  const totalCreditsUsed = history.reduce((s, j) => s + (j.cost || 0), 0);

  // Generate API Key
  const handleGenerateApiKey = async () => {
    if (!confirm("Tạo API key mới? Key cũ sẽ bị vô hiệu hóa.")) return;
    setGeneratingKey(true);
    try {
      const res = await api.generateApiKey();
      setProfile(prev => prev ? { ...prev, api_key: res.api_key } : null);
      showToast("✅ API Key mới đã tạo!", "success");
    } catch (e: any) {
      showToast(`❌ ${e.message}`, "error");
    } finally {
      setGeneratingKey(false);
    }
  };

  // Copy API Key
  const handleCopyApiKey = () => {
    if (profile?.api_key) {
      navigator.clipboard.writeText(profile.api_key);
      showToast("📋 Đã copy API Key!", "success");
    }
  };

  // Change Password
  const handleChangePassword = async () => {
    if (!currentPass || !newPass) return showToast("Vui lòng nhập đầy đủ", "error");
    if (newPass !== confirmPass) return showToast("Mật khẩu xác nhận không khớp", "error");
    if (newPass.length < 4) return showToast("Mật khẩu mới phải ít nhất 4 ký tự", "error");

    setChangingPass(true);
    try {
      await api.changePassword(currentPass, newPass);
      showToast("✅ Đổi mật khẩu thành công!", "success");
      setShowPassForm(false);
      setCurrentPass("");
      setNewPass("");
      setConfirmPass("");
    } catch (e: any) {
      showToast(`❌ ${e.message}`, "error");
    } finally {
      setChangingPass(false);
    }
  };

  if (!user) return null;

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Toast />
      <Navbar />
      <main className="pt-20 px-4 sm:px-6 max-w-4xl mx-auto pb-12">

        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center text-2xl font-bold"
            style={{ background: "var(--gradient-neon)", color: "white" }}>
            {user.username[0].toUpperCase()}
          </div>
          <div>
            <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
              {profile?.username || user.username}
            </h1>
            <div className="flex items-center gap-3 mt-1">
              <span className="badge badge-neon !text-xs">{profile?.role || user.role}</span>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                Tham gia từ {profile?.created_at ? new Date(profile.created_at).toLocaleDateString("vi-VN") : "..."}
              </span>
            </div>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 mb-8">
          {[
            { label: "Số dư", value: `${(profile?.balance ?? user.balance).toLocaleString()}`, icon: "diamond", color: "var(--neon-blue)", suffix: "credits" },
            { label: "Tổng tạo", value: `${totalJobs}`, icon: "work_history", color: "var(--neon-purple)", suffix: "lần" },
            { label: "Thành công", value: `${completedJobs}`, icon: "check_circle", color: "var(--success)", suffix: "lần" },
            { label: "Video", value: `${videoJobs}`, icon: "movie", color: "#06b6d4", suffix: "video" },
            { label: "Ảnh", value: `${imageJobs}`, icon: "image", color: "#f59e0b", suffix: "ảnh" },
            { label: "Đã dùng", value: `${totalCreditsUsed.toLocaleString()}`, icon: "toll", color: "var(--error)", suffix: "credits" },
          ].map((stat, i) => (
            <div key={i} className="rounded-xl p-5 text-center" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}>
              <span className="material-symbols-rounded text-2xl mb-2 block" style={{ color: stat.color }}>{stat.icon}</span>
              <p className="text-2xl font-bold mb-0.5" style={{ color: stat.color }}>{stat.value}</p>
              <p className="text-[11px] font-medium" style={{ color: "var(--text-muted)" }}>{stat.suffix}</p>
              <p className="text-[10px] font-semibold uppercase tracking-wider mt-1" style={{ color: "var(--text-muted)" }}>{stat.label}</p>
            </div>
          ))}
        </div>

        {/* Two columns */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* ═══ LEFT: API Key ═══ */}
          <div className="rounded-xl p-6" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}>
            <h3 className="text-sm font-bold mb-4 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <span className="material-symbols-rounded text-lg" style={{ color: "var(--neon-blue)" }}>key</span>
              API Key
            </h3>

            {profile?.api_key ? (
              <div className="space-y-3">
                <div className="rounded-lg p-3 flex items-center gap-2" style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border-subtle)" }}>
                  <code className="flex-1 text-xs font-mono truncate" style={{ color: "var(--text-secondary)" }}>
                    {showApiKey ? profile.api_key : `${profile.api_key.slice(0, 8)}${"•".repeat(30)}`}
                  </code>
                  <button onClick={() => setShowApiKey(!showApiKey)} className="btn-ghost !p-1.5 !rounded-lg" title={showApiKey ? "Ẩn" : "Hiện"}>
                    <span className="material-symbols-rounded text-sm" style={{ color: "var(--text-muted)" }}>
                      {showApiKey ? "visibility_off" : "visibility"}
                    </span>
                  </button>
                  <button onClick={handleCopyApiKey} className="btn-ghost !p-1.5 !rounded-lg" title="Copy">
                    <span className="material-symbols-rounded text-sm" style={{ color: "var(--neon-blue)" }}>content_copy</span>
                  </button>
                </div>
              </div>
            ) : (
              <div className="text-center py-4">
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>API Key chưa được tạo. Liên hệ admin.</p>
              </div>
            )}

            <div className="mt-4 rounded-lg p-3" style={{ background: "rgba(99,102,241,0.06)", border: "1px solid rgba(99,102,241,0.15)" }}>
              <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                <span className="material-symbols-rounded text-xs align-middle mr-1" style={{ color: "var(--neon-blue)" }}>info</span>
                API Key dùng để kết nối từ tool bên ngoài. Giữ bí mật, không chia sẻ.
              </p>
            </div>
          </div>

          {/* ═══ RIGHT: Change Password ═══ */}
          <div className="rounded-xl p-6" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}>
            <h3 className="text-sm font-bold mb-4 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <span className="material-symbols-rounded text-lg" style={{ color: "var(--neon-purple)" }}>lock</span>
              Bảo mật
            </h3>

            {!showPassForm ? (
              <button onClick={() => setShowPassForm(true)}
                className="flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all w-full"
                style={{ background: "var(--bg-tertiary)", color: "var(--text-primary)", border: "1px solid var(--border-subtle)" }}
                onMouseEnter={e => e.currentTarget.style.background = "var(--bg-hover)"}
                onMouseLeave={e => e.currentTarget.style.background = "var(--bg-tertiary)"}>
                <span className="material-symbols-rounded text-lg" style={{ color: "var(--neon-purple)" }}>password</span>
                Đổi mật khẩu
              </button>
            ) : (
              <div className="space-y-3">
                <input type="password" value={currentPass} onChange={e => setCurrentPass(e.target.value)}
                  className="input-field !py-2.5 !text-sm" placeholder="Mật khẩu hiện tại"
                  style={{ background: "var(--bg-input)" }} />
                <input type="password" value={newPass} onChange={e => setNewPass(e.target.value)}
                  className="input-field !py-2.5 !text-sm" placeholder="Mật khẩu mới"
                  style={{ background: "var(--bg-input)" }} />
                <input type="password" value={confirmPass} onChange={e => setConfirmPass(e.target.value)}
                  className="input-field !py-2.5 !text-sm" placeholder="Xác nhận mật khẩu mới"
                  style={{ background: "var(--bg-input)" }}
                  onKeyDown={e => e.key === "Enter" && handleChangePassword()} />
                <div className="flex items-center gap-2 pt-1">
                  <button onClick={handleChangePassword} disabled={changingPass}
                    className="btn-generate !py-2 !px-4 !text-xs flex items-center gap-2">
                    {changingPass ? <span className="spinner !w-3 !h-3 !border-white/20 !border-t-white"></span> : <span className="material-symbols-rounded text-sm">save</span>}
                    Lưu
                  </button>
                  <button onClick={() => { setShowPassForm(false); setCurrentPass(""); setNewPass(""); setConfirmPass(""); }}
                    className="btn-ghost !py-2 !px-4 !text-xs">
                    Hủy
                  </button>
                </div>
              </div>
            )}

            {/* Account info */}
            <div className="mt-6 space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Thông tin tài khoản</p>
              {[
                { label: "Username", value: profile?.username || "..." },
                { label: "Email", value: profile?.email || "Chưa có" },
                { label: "Role", value: profile?.role || user.role },
                { label: "Trạng thái", value: profile?.is_banned ? "🔒 Bị khóa" : "✅ Hoạt động" },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between py-1.5" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <span className="text-xs" style={{ color: "var(--text-muted)" }}>{item.label}</span>
                  <span className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>{item.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Link to API Docs */}
        <div className="mt-8 rounded-xl p-5 flex items-center justify-between" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}>
          <div className="flex items-center gap-3">
            <span className="material-symbols-rounded text-2xl" style={{ color: "#06b6d4" }}>code</span>
            <div>
              <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>API Documentation</h3>
              <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>Xem tài liệu kết nối API</p>
            </div>
          </div>
          <a href="/docs" className="btn-generate !py-2 !px-4 !text-xs flex items-center gap-1.5 no-underline">
            <span className="material-symbols-rounded text-sm">open_in_new</span>
            Xem Docs
          </a>
        </div>

      </main>
    </div>
  );
}
