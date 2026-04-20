/**
 * Login Page — UltraFlow AI
 * Dark mode neon design
 */
"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";

export default function LoginPage() {
  const [isLogin, setIsLogin] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const router = useRouter();
  const setUser = useStore((s) => s.setUser);

  // Clear stale tokens on login page mount
  useEffect(() => {
    localStorage.removeItem("veo3_token");
    localStorage.removeItem("veo3_user");
  }, []);

  const [success, setSuccess] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);

    try {
      if (isLogin) {
        const data = await api.login(username, password);
        setUser({
          user_id: data.user_id || 0,
          username: data.username,
          role: data.role,
          balance: data.balance,
          token: data.access_token,
        });
        router.push("/");
      } else {
        await api.register(username, password);
        setSuccess("🎉 Đăng ký thành công! Vui lòng đăng nhập.");
        setIsLogin(true);
      }
    } catch (e: any) {
      setError(e.message || "Đã xảy ra lỗi");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden"
      style={{ background: "var(--bg-primary)" }}>

      {/* Background glow effects */}
      <div className="absolute top-1/4 left-1/4 w-96 h-96 rounded-full blur-[120px] opacity-20"
        style={{ background: "var(--neon-blue)" }} />
      <div className="absolute bottom-1/4 right-1/4 w-80 h-80 rounded-full blur-[120px] opacity-15"
        style={{ background: "var(--neon-purple)" }} />

      <div className="w-full max-w-md relative z-10">
        {/* Logo */}
        <div className="text-center mb-10">
          <img src="/logo.png" alt="Veo3Lab" className="mx-auto mb-4 object-contain rounded-2xl" style={{ height: 80, maxWidth: 160, boxShadow: "0 4px 24px rgba(0,0,0,0.3)" }} />
          <h1 className="text-3xl font-extrabold tracking-tight">
            <span className="gradient-text">Veo3</span>
            <span style={{ color: "var(--text-primary)" }}>Lab</span>
          </h1>
          <p className="text-sm mt-2" style={{ color: "var(--text-muted)" }}>
            AI Video Generate Platform
          </p>
        </div>

        {/* Form card */}
        <div className="glass-card p-7" style={{ boxShadow: "0 0 60px rgba(99, 102, 241, 0.05)" }}>
          {/* Toggle tabs */}
          <div className="flex rounded-xl overflow-hidden mb-7 p-1"
            style={{ background: "var(--bg-tertiary)" }}>
            {[
              { key: true, label: "Đăng nhập", icon: "login" },
              { key: false, label: "Đăng ký", icon: "person_add" },
            ].map((tab) => (
              <button
                key={String(tab.key)}
                onClick={() => setIsLogin(tab.key)}
                className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-lg text-sm font-medium transition-all"
                style={{
                  background: isLogin === tab.key ? "rgba(99, 102, 241, 0.15)" : "transparent",
                  color: isLogin === tab.key ? "var(--neon-blue)" : "var(--text-muted)",
                }}
              >
                <span className="material-symbols-rounded text-lg">{tab.icon}</span>
                {tab.label}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="text-xs font-medium mb-2 block" style={{ color: "var(--text-muted)" }}>
                Tên đăng nhập
              </label>
              <input
                type="text" value={username} onChange={(e) => setUsername(e.target.value)}
                className="input-field" placeholder="username" required minLength={3} autoFocus
              />
            </div>

            <div>
              <label className="text-xs font-medium mb-2 block" style={{ color: "var(--text-muted)" }}>
                Mật khẩu
              </label>
              <input
                type="password" value={password} onChange={(e) => setPassword(e.target.value)}
                className="input-field" placeholder="••••••••" required minLength={4}
              />
            </div>

            {success && (
              <div className="text-sm px-4 py-3 rounded-xl flex items-center gap-2"
                style={{ background: "rgba(34,197,94,0.08)", color: "#22c55e", border: "1px solid rgba(34,197,94,0.2)" }}>
                <span className="material-symbols-rounded text-lg">check_circle</span>
                {success}
              </div>
            )}

            {error && (
              <div className="text-sm px-4 py-3 rounded-xl flex items-center gap-2"
                style={{ background: "rgba(248,113,113,0.08)", color: "var(--error)", border: "1px solid rgba(248,113,113,0.2)" }}>
                <span className="material-symbols-rounded text-lg">error</span>
                {error}
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-generate w-full flex items-center justify-center gap-2">
              {loading ? (
                <span className="spinner !w-5 !h-5 !border-white/20 !border-t-white"></span>
              ) : (
                <span className="material-symbols-rounded text-xl">
                  {isLogin ? "arrow_forward" : "person_add"}
                </span>
              )}
              {loading ? "Đang xử lý..." : isLogin ? "Đăng nhập" : "Tạo tài khoản"}
            </button>
          </form>
        </div>

        <p className="text-xs text-center mt-8" style={{ color: "var(--text-muted)" }}>
          Powered by Veo 3.1 Ultra · Veo3LabAI.com
        </p>
      </div>
    </div>
  );
}
