/**
 * Toast — Notification popup (UltraFlow style)
 */
"use client";
import { useStore } from "@/lib/store";

export function Toast() {
  const toast = useStore((s) => s.toast);
  if (!toast) return null;

  const styles = {
    success: { bg: "rgba(52, 211, 153, 0.08)", border: "rgba(52, 211, 153, 0.2)", color: "#34d399" },
    error: { bg: "rgba(248, 113, 113, 0.08)", border: "rgba(248, 113, 113, 0.2)", color: "#f87171" },
    info: { bg: "rgba(99, 102, 241, 0.08)", border: "rgba(99, 102, 241, 0.2)", color: "#6366f1" },
  };
  const s = styles[toast.type];

  return (
    <div className="fixed top-20 right-4 z-[100]" style={{ animation: "slideIn 0.3s ease" }}>
      <div className="px-5 py-3 rounded-xl backdrop-blur-xl text-sm font-medium flex items-center gap-2"
        style={{ background: s.bg, border: `1px solid ${s.border}`, color: s.color, boxShadow: `0 0 20px ${s.bg}` }}>
        <span className="material-symbols-rounded text-lg">
          {toast.type === "success" ? "check_circle" : toast.type === "error" ? "error" : "info"}
        </span>
        {toast.message}
      </div>
    </div>
  );
}
