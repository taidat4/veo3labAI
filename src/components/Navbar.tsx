/**
 * Navbar — Top navigation bar (cố định)
 * Logo "UltraFlow AI" | Create Video | My Videos | Queue | Credits | Avatar
 */
"use client";
import { useStore } from "@/lib/store";
import { useRouter, usePathname } from "next/navigation";

const NAV_ITEMS = [
  { label: "Tạo Video", href: "/", icon: "movie_creation" },
  { label: "Video của tôi", href: "/videos", icon: "video_library" },
  { label: "Ảnh của tôi", href: "/images", icon: "photo_library" },
  { label: "Hàng chờ", href: "/queue", icon: "schedule" },
  { label: "Gói Đăng Ký", href: "/plans", icon: "workspace_premium", accent: true },
];

export function Navbar() {
  const router = useRouter();
  const pathname = usePathname();
  const user = useStore((s) => s.user);
  const logout = useStore((s) => s.logout);
  const theme = useStore((s) => s.theme);
  const toggleTheme = useStore((s) => s.toggleTheme);

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 h-16 flex items-center px-6"
      style={{
        background: "var(--bg-card-solid)",
        backdropFilter: "blur(20px) saturate(1.4)",
        borderBottom: "1px solid var(--border-medium)",
        boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
      }}>

      {/* Logo */}
      <button onClick={() => router.push("/")} className="flex items-center gap-2.5 mr-8 group">
        <img src="/logo.png" alt="Veo3Lab" className="h-9 w-auto object-contain rounded-lg" />
        <span className="text-[15px] font-bold tracking-tight">
          <span className="gradient-text">Veo3</span>
          <span style={{ color: "var(--text-primary)" }}>Lab</span>
        </span>
      </button>

      {/* Nav items */}
      <div className="flex items-center gap-1">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          const isAccent = (item as any).accent;
          return (
            <button
              key={item.href}
              onClick={() => router.push(item.href)}
              className={`neon-underline flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${isActive ? 'active' : ''}`}
              style={{
                color: isActive
                  ? (isAccent ? "#10b981" : "var(--neon-blue)")
                  : (isAccent ? "#10b981" : "var(--text-secondary)"),
                background: isActive
                  ? (isAccent ? "rgba(16,185,129,0.1)" : "rgba(99, 102, 241, 0.08)")
                  : "transparent",
                fontWeight: isAccent ? 600 : undefined,
              }}
              onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.color = isAccent ? "#34d399" : "var(--text-primary)"; }}
              onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.color = isAccent ? "#10b981" : "var(--text-secondary)"; }}
            >
              <span className="material-symbols-rounded text-lg">{item.icon}</span>
              <span className="hidden sm:inline">{item.label}</span>
            </button>
          );
        })}
      </div>

      {/* Right side: Số Dư + avatar */}
      <div className="ml-auto flex items-center gap-3">
        {user && (
          <>
            {/* Credits */}
            <div className="badge badge-neon !text-sm !py-1.5 !px-3" style={{ background: "rgba(168,85,247,0.12)", border: "1px solid rgba(168,85,247,0.3)" }}>
              <span className="material-symbols-rounded text-sm" style={{ color: "#a855f7" }}>bolt</span>
              <span style={{ color: "#a855f7", fontWeight: 700 }}>{(user.credits ?? 0).toLocaleString()}</span>
              <span style={{ color: "var(--text-muted)", fontSize: "10px" }}>credits</span>
            </div>
            {/* Số Dư VND */}
            <div className="badge badge-neon !text-sm !py-1.5 !px-3">
              <span className="material-symbols-rounded text-sm">account_balance_wallet</span>
              <span style={{ fontWeight: 700 }}>{(user.balance ?? 0).toLocaleString()}đ</span>
            </div>

            {/* Theme toggle */}
            <button onClick={toggleTheme}
              className="btn-ghost !p-2" title={theme === "dark" ? "Sáng" : "Tối"}>
              <span className="material-symbols-rounded text-lg" style={{ color: "var(--text-secondary)" }}>
                {theme === "dark" ? "light_mode" : "dark_mode"}
              </span>
            </button>



            {/* Avatar dropdown */}
            <div className="relative group">
              <button className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold transition-all"
                style={{
                  background: "var(--gradient-subtle)",
                  color: "var(--neon-blue)",
                  border: "1px solid var(--border-accent)",
                }}>
                {user.username[0].toUpperCase()}
              </button>

              {/* Dropdown */}
              <div className="absolute right-0 top-full mt-2 w-48 rounded-xl overflow-hidden opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200"
                style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", boxShadow: "var(--shadow-dropdown)" }}>
                <div className="px-4 py-3" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
                  <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{user.username}</p>
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>{user.role}</p>
                </div>
                <button onClick={() => router.push("/profile")}
                  className="w-full text-left px-4 py-2.5 text-sm flex items-center gap-2 transition-colors"
                  style={{ color: "var(--text-secondary)" }}
                  onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg-hover)"}
                  onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                  <span className="material-symbols-rounded text-lg">person</span>
                  Trang cá nhân
                </button>
                <button onClick={() => { logout(); router.push("/login"); }}
                  className="w-full text-left px-4 py-2.5 text-sm flex items-center gap-2 transition-colors"
                  style={{ color: "var(--error)" }}
                  onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg-hover)"}
                  onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                  <span className="material-symbols-rounded text-lg">logout</span>
                  Đăng xuất
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </nav>
  );
}
