/**
 * MobileLayout — Giao diện mobile riêng biệt cho Veo3Lab
 * Hiển thị khi screen < 768px. KHÔNG đụng desktop layout.
 * 
 * Layout: 
 *   - Top: Compact navbar (logo + credits + menu)
 *   - Middle: Scrollable content (active jobs + media grid)
 *   - Bottom: Fixed prompt input bar
 */
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useStore, type HistoryJob } from "@/lib/store";
import { api } from "@/lib/api";
import { VideoPreviewModal } from "@/components/VideoPreviewModal";

export function MobileLayout({
  activeJobList,
  completedJobs,
  allCompleted,
  videoCount,
  imageCount,
  contentFilter,
  setContentFilter,
}: {
  activeJobList: any[];
  completedJobs: HistoryJob[];
  allCompleted: HistoryJob[];
  videoCount: number;
  imageCount: number;
  contentFilter: "all" | "video" | "image";
  setContentFilter: (f: "all" | "video" | "image") => void;
}) {
  const router = useRouter();
  const user = useStore((s) => s.user);
  const showToast = useStore((s) => s.showToast);
  const [showSettings, setShowSettings] = useState(false);
  const [showMenu, setShowMenu] = useState(false);

  // ── Prompt state (local — not in store) ──
  const [prompt, setPrompt] = useState("");
  const mediaTab = useStore((s) => s.mediaTab);
  const setMediaTab = useStore((s) => s.setMediaTab);

  const handleGenerate = async () => {
    if (!prompt.trim()) return showToast("Nhập prompt trước!", "error");
    const store = useStore.getState();
    const settings = {
      mediaType: store.mediaTab,
      aspectRatio: store.aspectRatio,
      numVideos: store.numberOfOutputs,
    };
    try {
      const resp = await api.generate(prompt, settings);
      if (resp.jobs) {
        for (const job of resp.jobs) {
          store.addActiveJob({
            id: job.id,
            prompt: prompt,
            status: "queued",
            progress: 0,
            mediaType: settings.mediaType,
            startedAt: Date.now(),
          });
        }
        showToast(`🚀 Đang tạo ${settings.mediaType === "image" ? "ảnh" : "video"}...`, "success");
        setPrompt("");
      }
    } catch (err: any) {
      showToast(`❌ ${err?.message || "Lỗi tạo"}`, "error");
    }
  };

  return (
    <div className="mobile-app">
      {/* ═══ MOBILE NAVBAR ═══ */}
      <header className="mobile-navbar">
        <div className="flex items-center gap-2">
          <img src="/favicon.png" alt="Logo" className="w-8 h-8 rounded-lg" />
          <span className="font-bold text-base gradient-text">Veo3Lab</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="mobile-credits">
            <span className="material-symbols-rounded" style={{ fontSize: 14, color: "var(--neon-blue)" }}>bolt</span>
            <span>{(user?.credits || 0).toLocaleString()}</span>
          </div>
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="mobile-icon-btn"
          >
            <span className="material-symbols-rounded">{showMenu ? "close" : "menu"}</span>
          </button>
        </div>
      </header>

      {/* ═══ MOBILE MENU OVERLAY ═══ */}
      {showMenu && (
        <>
          <div className="mobile-overlay" onClick={() => setShowMenu(false)} />
          <nav className="mobile-menu">
            <button onClick={() => { router.push("/"); setShowMenu(false); }} className="mobile-menu-item">
              <span className="material-symbols-rounded">home</span>
              Trang chủ
            </button>
            <button onClick={() => { router.push("/videos"); setShowMenu(false); }} className="mobile-menu-item">
              <span className="material-symbols-rounded">movie</span>
              My Videos
            </button>
            <button onClick={() => { router.push("/images"); setShowMenu(false); }} className="mobile-menu-item">
              <span className="material-symbols-rounded">image</span>
              My Images
            </button>
            <div className="mobile-menu-divider" />
            <button onClick={() => { setShowSettings(true); setShowMenu(false); }} className="mobile-menu-item">
              <span className="material-symbols-rounded">tune</span>
              Cài đặt tạo
            </button>
            <button onClick={() => {
              const current = document.documentElement.classList.contains("dark");
              document.documentElement.classList.toggle("dark");
              localStorage.setItem("veo3_theme", current ? "light" : "dark");
              setShowMenu(false);
            }} className="mobile-menu-item">
              <span className="material-symbols-rounded">
                {typeof document !== "undefined" && document.documentElement.classList.contains("dark") ? "light_mode" : "dark_mode"}
              </span>
              Đổi theme
            </button>
            <div className="mobile-menu-divider" />
            <div className="px-4 py-2 text-xs" style={{ color: "var(--text-muted)" }}>
              💰 Số dư: {((user?.balance || 0) / 1000).toFixed(1)}K₫ · {(user?.credits || 0).toLocaleString()} credits
            </div>
          </nav>
        </>
      )}

      {/* ═══ MOBILE SETTINGS BOTTOM SHEET ═══ */}
      {showSettings && (
        <MobileSettingsSheet onClose={() => setShowSettings(false)} />
      )}

      {/* ═══ MOBILE CONTENT ═══ */}
      <div className="mobile-content">
        {/* Media tabs */}
        <div className="mobile-tabs">
          {([
            { key: "all" as const, label: "Tất cả", count: allCompleted.length, icon: "apps" },
            { key: "video" as const, label: "Video", count: videoCount, icon: "movie" },
            { key: "image" as const, label: "Ảnh", count: imageCount, icon: "image" },
          ]).map((tab) => (
            <button
              key={tab.key}
              onClick={() => setContentFilter(tab.key)}
              className={`mobile-tab ${contentFilter === tab.key ? "active" : ""}`}
            >
              <span className="material-symbols-rounded" style={{ fontSize: 16 }}>{tab.icon}</span>
              {tab.label} ({tab.count})
            </button>
          ))}
        </div>

        {/* Active jobs */}
        {activeJobList.length > 0 && (
          <div className="mobile-section">
            <div className="flex items-center gap-2 mb-3">
              <span className="pulse-dot" />
              <span className="text-xs font-semibold" style={{ color: "var(--text-muted)" }}>
                Đang xử lý ({activeJobList.length})
              </span>
            </div>
            {activeJobList.map((job) => (
              <MobileActiveJob key={job.id} job={job} />
            ))}
          </div>
        )}

        {/* Media grid — 2 columns on mobile */}
        {completedJobs.length > 0 ? (
          <div className="mobile-grid">
            {completedJobs.slice(0, 30).map((job) => (
              <MobileMediaCard key={job.id} job={job} />
            ))}
          </div>
        ) : (
          <div className="mobile-empty">
            <span className="material-symbols-rounded" style={{ fontSize: 48, color: "var(--text-muted)" }}>
              video_library
            </span>
            <p className="text-sm mt-3" style={{ color: "var(--text-muted)" }}>Chưa có nội dung nào</p>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Nhập prompt bên dưới để bắt đầu</p>
          </div>
        )}
      </div>

      {/* ═══ MOBILE PROMPT BAR (fixed bottom) ═══ */}
      <div className="mobile-prompt-bar">
        {/* Type toggle */}
        <button
          onClick={() => setMediaTab(mediaTab === "video" ? "image" : "video")}
          className="mobile-type-toggle"
          title={mediaTab === "video" ? "Video" : "Ảnh"}
        >
          <span className="material-symbols-rounded" style={{ fontSize: 20 }}>
            {mediaTab === "video" ? "movie" : "image"}
          </span>
        </button>
        <input
          type="text"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleGenerate(); } }}
          placeholder={mediaTab === "video" ? "Mô tả video..." : "Mô tả ảnh..."}
          className="mobile-prompt-input"
        />
        <button
          onClick={() => setShowSettings(true)}
          className="mobile-icon-btn"
          style={{ color: "var(--text-muted)" }}
        >
          <span className="material-symbols-rounded" style={{ fontSize: 20 }}>tune</span>
        </button>
        <button
          onClick={handleGenerate}
          disabled={!prompt.trim()}
          className="mobile-generate-btn"
        >
          <span className="material-symbols-rounded" style={{ fontSize: 20 }}>send</span>
        </button>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════════
 * Mobile Sub-Components
 * ═══════════════════════════════════════════════════════════════════════════════ */

function MobileActiveJob({ job }: { job: any }) {
  return (
    <div className="mobile-active-job">
      <div className="mobile-progress-ring">
        <svg viewBox="0 0 36 36" className="w-9 h-9">
          <circle cx="18" cy="18" r="15.5" fill="none" stroke="var(--bg-tertiary)" strokeWidth="3" />
          <circle
            cx="18" cy="18" r="15.5" fill="none"
            stroke="url(#mobileGrad)" strokeWidth="3"
            strokeDasharray={`${(job.progress || 0) * 0.975} 97.5`}
            strokeLinecap="round"
            style={{ transform: "rotate(-90deg)", transformOrigin: "center" }}
          />
          <defs>
            <linearGradient id="mobileGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="var(--neon-blue)" />
              <stop offset="100%" stopColor="var(--neon-purple)" />
            </linearGradient>
          </defs>
        </svg>
        <span className="mobile-progress-text">{Math.round(job.progress || 0)}%</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium truncate" style={{ color: "var(--text-primary)" }}>{job.prompt}</p>
        <p className="text-[10px] mt-0.5" style={{ color: "var(--text-muted)" }}>
          {job.status === "failed" ? `❌ ${job.error || "Thất bại"}` : `⏳ ${job.mediaType === "image" ? "Ảnh" : "Video"}...`}
        </p>
      </div>
    </div>
  );
}

function MobileMediaCard({ job }: { job: HistoryJob }) {
  const [showPreview, setShowPreview] = useState(false);
  const mediaUrl = job.video_url || job.r2_url;
  const isImage = job.media_type === "image";

  if (!mediaUrl) return null;

  return (
    <>
      <div className="mobile-card" onClick={() => setShowPreview(true)}>
        <div className="mobile-card-media">
          {isImage ? (
            <img src={job.thumbnail_url || mediaUrl} alt="" className="w-full h-full object-cover" loading="lazy" decoding="async" />
          ) : (
            <video src={mediaUrl} className="w-full h-full object-cover" preload="none" muted playsInline />
          )}
          {/* Badge */}
          <div className="absolute top-1 right-1">
            <span className="mobile-badge">{isImage ? "IMG" : "HD"}</span>
          </div>
          {/* Play icon for video */}
          {!isImage && (
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="material-symbols-rounded text-white text-2xl" style={{ textShadow: "0 2px 8px rgba(0,0,0,0.5)" }}>
                play_circle
              </span>
            </div>
          )}
        </div>
        <div className="mobile-card-info">
          <p className="text-[11px] font-medium truncate" style={{ color: "var(--text-primary)" }}>{job.prompt}</p>
          <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>
            {new Date(job.created_at).toLocaleDateString("vi-VN")} · {job.cost} cr
          </p>
        </div>
      </div>
      {showPreview && (
        <VideoPreviewModal job={job} onClose={() => setShowPreview(false)} />
      )}
    </>
  );
}

function MobileSettingsSheet({ onClose }: { onClose: () => void }) {
  const mediaTab = useStore((s) => s.mediaTab);
  const setMediaTab = useStore((s) => s.setMediaTab);
  const aspectRatio = useStore((s) => s.aspectRatio);
  const setAspectRatio = useStore((s) => s.setAspectRatio);
  const numberOfOutputs = useStore((s) => s.numberOfOutputs);
  const setNumberOfOutputs = useStore((s) => s.setNumberOfOutputs);

  return (
    <>
      <div className="mobile-overlay" onClick={onClose} />
      <div className="mobile-bottom-sheet">
        <div className="mobile-sheet-handle" />
        <h3 className="text-sm font-semibold mb-4" style={{ color: "var(--text-primary)" }}>Cài đặt</h3>

        {/* Media type */}
        <div className="mb-4">
          <label className="text-xs font-medium mb-2 block" style={{ color: "var(--text-muted)" }}>Loại</label>
          <div className="flex gap-2">
            {(["video", "image"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setMediaTab(t)}
                className={`mobile-setting-chip ${mediaTab === t ? "active" : ""}`}
              >
                <span className="material-symbols-rounded" style={{ fontSize: 16 }}>{t === "video" ? "movie" : "image"}</span>
                {t === "video" ? "Video" : "Ảnh"}
              </button>
            ))}
          </div>
        </div>

        {/* Aspect ratio */}
        <div className="mb-4">
          <label className="text-xs font-medium mb-2 block" style={{ color: "var(--text-muted)" }}>Tỷ lệ</label>
          <div className="flex gap-2 flex-wrap">
            {(["16:9", "9:16", "1:1"] as const).map((ar) => (
              <button
                key={ar}
                onClick={() => setAspectRatio(ar)}
                className={`mobile-setting-chip ${aspectRatio === ar ? "active" : ""}`}
              >
                {ar}
              </button>
            ))}
          </div>
        </div>

        {/* Number of videos */}
        {mediaTab === "video" && (
          <div className="mb-4">
            <label className="text-xs font-medium mb-2 block" style={{ color: "var(--text-muted)" }}>Số lượng</label>
            <div className="flex gap-2">
              {[1, 2, 4].map((n) => (
                <button
                  key={n}
                  onClick={() => setNumberOfOutputs(n)}
                  className={`mobile-setting-chip ${numberOfOutputs === n ? "active" : ""}`}
                >
                  ×{n}
                </button>
              ))}
            </div>
          </div>
        )}

        <button onClick={onClose} className="w-full py-3 rounded-xl text-sm font-semibold text-white mt-2" style={{ background: "var(--gradient-neon)" }}>
          Xong
        </button>
      </div>
    </>
  );
}
