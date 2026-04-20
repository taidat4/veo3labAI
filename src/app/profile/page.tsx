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
                <button onClick={handleGenerateApiKey} disabled={generatingKey}
                  className="text-xs flex items-center gap-1.5 transition-colors"
                  style={{ color: "var(--neon-purple)" }}>
                  {generatingKey ? <span className="spinner !w-3 !h-3"></span> : <span className="material-symbols-rounded text-sm">refresh</span>}
                  Tạo key mới
                </button>
              </div>
            ) : (
              <div className="text-center py-4">
                <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>Chưa có API Key</p>
                <button onClick={handleGenerateApiKey} disabled={generatingKey}
                  className="btn-generate !py-2 !px-4 !text-xs flex items-center gap-2 mx-auto">
                  {generatingKey ? <span className="spinner !w-3 !h-3 !border-white/20 !border-t-white"></span> : <span className="material-symbols-rounded text-sm">add</span>}
                  Tạo API Key
                </button>
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

        {/* ═══ API Documentation ═══ */}
        <div className="mt-8 rounded-xl p-6" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}>
          <h3 className="text-sm font-bold mb-5 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
            <span className="material-symbols-rounded text-lg" style={{ color: "#06b6d4" }}>code</span>
            API Documentation
            <span className="badge !text-[9px] ml-1" style={{ background: "rgba(6,182,212,0.15)", color: "#06b6d4" }}>v1</span>
          </h3>

          {/* Base URL */}
          <div className="rounded-lg p-3 mb-5" style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border-subtle)" }}>
            <p className="text-[11px] font-semibold mb-1" style={{ color: "var(--text-muted)" }}>BASE URL</p>
            <code className="text-sm font-mono font-bold" style={{ color: "var(--neon-blue)" }}>
              https://veo3labai.com
            </code>
          </div>

          {/* Architecture note */}
          <div className="rounded-lg p-3 mb-5" style={{ background: "rgba(6,182,212,0.06)", border: "1px solid rgba(6,182,212,0.15)" }}>
            <p className="text-[11px] font-semibold mb-1" style={{ color: "#06b6d4" }}>🏗️ KIẾN TRÚC</p>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              Mọi request API đều đi qua <strong>veo3labai.com</strong> — server của chúng tôi xử lý toàn bộ yêu cầu, quản lý tài khoản và cân bằng tải tự động. Bạn không cần quan tâm đến backend, chỉ cần gọi API với API Key.
            </p>
          </div>

          {/* Auth header */}
          <div className="rounded-lg p-3 mb-5" style={{ background: "rgba(168,85,247,0.06)", border: "1px solid rgba(168,85,247,0.15)" }}>
            <p className="text-[11px] font-semibold mb-1" style={{ color: "var(--neon-purple)" }}>🔑 AUTHENTICATION</p>
            <p className="text-xs mb-2" style={{ color: "var(--text-secondary)" }}>Thêm header sau vào mọi request:</p>
            <pre className="text-xs font-mono rounded-md p-2.5 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-primary)" }}>
{`Authorization: Bearer <YOUR_API_KEY>`}
            </pre>
          </div>

          {/* Endpoints */}
          <div className="space-y-5">

            {/* 1. Generate Video */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#22c55e", color: "white" }}>POST</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/generate</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Tạo video</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`curl -X POST https://veo3labai.com/api/generate \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "prompt": "A cat playing piano",
    "aspect_ratio": "16:9",
    "video_model": "veo31_fast_lp",
    "number_of_outputs": 1
  }'`}
              </pre>
            </div>

            {/* 2. Generate Image */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#22c55e", color: "white" }}>POST</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/generate</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Tạo ảnh</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`curl -X POST https://veo3labai.com/api/generate \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "prompt": "A beautiful sunset over mountains",
    "video_model": "imagen_4",
    "resolution": "1024x1024"
  }'`}
              </pre>
            </div>

            {/* 3. Bulk Generate */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#22c55e", color: "white" }}>POST</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/generate/bulk</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Tạo hàng loạt</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`curl -X POST https://veo3labai.com/api/generate/bulk \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "prompts": [
      "Prompt 1...",
      "Prompt 2...",
      "Prompt 3..."
    ],
    "aspect_ratio": "16:9",
    "video_model": "veo31_fast_lp"
  }'`}
              </pre>
            </div>

            {/* 4. Get Job Status */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#3b82f6", color: "white" }}>GET</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/job/{"{job_id}"}</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Kiểm tra trạng thái</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`curl https://veo3labai.com/api/job/123 \\
  -H "Authorization: Bearer YOUR_API_KEY"

# Response:
# {
#   "id": 123,
#   "status": "completed",  // pending | processing | completed | failed
#   "video_url": "https://...",
#   "r2_url": "https://...",
#   "cost": 2000,
#   "media_type": "video"
# }`}
              </pre>
            </div>

            {/* 5. List Jobs */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#3b82f6", color: "white" }}>GET</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/jobs?limit=50&offset=0</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Danh sách jobs</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`curl "https://veo3labai.com/api/jobs?limit=50&offset=0" \\
  -H "Authorization: Bearer YOUR_API_KEY"`}
              </pre>
            </div>

            {/* 6. Download */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#3b82f6", color: "white" }}>GET</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/download/{"{job_id}"}?quality=720</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Tải video/ảnh</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`# quality: "720" (mặc định) hoặc "1080" (cần upscale trước)
curl -o video.mp4 \\
  "https://veo3labai.com/api/download/123?quality=720&token=YOUR_API_KEY"`}
              </pre>
            </div>
          </div>

          {/* JavaScript Example */}
          <div className="mt-6 rounded-lg overflow-hidden" style={{ border: "1px solid rgba(99,102,241,0.3)" }}>
            <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "rgba(99,102,241,0.08)" }}>
              <span className="material-symbols-rounded text-sm" style={{ color: "var(--neon-blue)" }}>javascript</span>
              <span className="text-xs font-semibold" style={{ color: "var(--neon-blue)" }}>JavaScript / Node.js Example</span>
            </div>
            <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`const API_KEY = "YOUR_API_KEY";
const BASE = "https://veo3labai.com";

// Tạo video
const res = await fetch(\`\${BASE}/api/generate\`, {
  method: "POST",
  headers: {
    "Authorization": \`Bearer \${API_KEY}\`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    prompt: "A cat playing piano",
    aspect_ratio: "16:9",
    video_model: "veo31_fast_lp"
  })
});
const { job_id } = await res.json();

// Kiểm tra trạng thái (polling)
const check = async () => {
  const r = await fetch(\`\${BASE}/api/job/\${job_id}\`, {
    headers: { "Authorization": \`Bearer \${API_KEY}\` }
  });
  const job = await r.json();
  if (job.status === "completed") {
    console.log("Video URL:", job.video_url);
  } else if (job.status === "failed") {
    console.log("Error:", job.error);
  } else {
    setTimeout(check, 5000); // Thử lại sau 5s
  }
};
check();`}
            </pre>
          </div>

          {/* Models table */}
          <div className="mt-6">
            <p className="text-[11px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>Models có sẵn</p>
            <div className="overflow-x-auto rounded-lg" style={{ border: "1px solid var(--border-subtle)" }}>
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ background: "var(--bg-tertiary)" }}>
                    <th className="text-left px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Model Key</th>
                    <th className="text-left px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Loại</th>
                    <th className="text-left px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Mô tả</th>
                    <th className="text-right px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Credit</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { key: "veo31_fast_lp", type: "🎬 Video", desc: "Veo 3.1 Quality", credit: "1" },
                    { key: "nano_banana_pro", type: "🖼️ Image", desc: "Nano Banana Pro", credit: "1" },
                    { key: "nano_banana_2", type: "🖼️ Image", desc: "Nano Banana 2", credit: "1" },
                    { key: "imagen_4", type: "🖼️ Image", desc: "Imagen 4 (cao cấp)", credit: "1" },
                  ].map((m, i) => (
                    <tr key={i} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                      <td className="px-4 py-2.5 font-mono font-semibold" style={{ color: "var(--neon-blue)" }}>{m.key}</td>
                      <td className="px-4 py-2.5" style={{ color: "var(--text-secondary)" }}>{m.type}</td>
                      <td className="px-4 py-2.5" style={{ color: "var(--text-secondary)" }}>{m.desc}</td>
                      <td className="px-4 py-2.5 text-right font-semibold" style={{ color: "var(--neon-purple)" }}>{m.credit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Rate limits note */}
          <div className="mt-5 rounded-lg p-3" style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.15)" }}>
            <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
              <span className="material-symbols-rounded text-xs align-middle mr-1" style={{ color: "#f59e0b" }}>warning</span>
              <strong>Rate Limit:</strong> Tối đa 9 request đồng thời. Sử dụng polling (5-10s) để kiểm tra trạng thái job thay vì gửi request liên tục.
            </p>
          </div>
        </div>

      </main>
    </div>
  );
}
