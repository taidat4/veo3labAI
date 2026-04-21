/**
 * Create Video Page — Main UltraFlow AI page
 * Layout: Navbar + [LEFT: SettingsPanel] + [RIGHT: Grid Videos + Active Jobs]
 * PromptBox fixed at bottom (sticky, always visible)
 */
"use client";
import { useEffect, useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import { useWebSocket } from "@/lib/useWebSocket";
import { Navbar } from "@/components/Navbar";
import { SettingsPanel } from "@/components/SettingsPanel";
import { PromptBox } from "@/components/PromptBox";
import { ActiveJobCard } from "@/components/ProgressCircle";
import { VideoCard } from "@/components/VideoCard";
import { Toast } from "@/components/Toast";

const GRID_MODES = [
  { cols: 2, icon: "grid_on", label: "2 cột" },
  { cols: 3, icon: "grid_view", label: "3 cột" },
  { cols: 4, icon: "apps", label: "4 cột" },
  { cols: 6, icon: "view_comfy", label: "6 cột" },
  { cols: 8, icon: "view_compact", label: "8 cột" },
] as const;

export default function HomePage() {
  const router = useRouter();
  const user = useStore((s) => s.user);
  const setUser = useStore((s) => s.setUser);
  const history = useStore((s) => s.history);
  const setHistory = useStore((s) => s.setHistory);
  const activeJobs = useStore((s) => s.activeJobs);
  const [gridCols, setGridCols] = useState(6);
  const [showGridPopup, setShowGridPopup] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const storeMediaTab = useStore((s) => s.mediaTab); // "video" | "image" from sidebar
  const [contentFilter, setContentFilter] = useState<"all" | "video" | "image">(storeMediaTab);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // WebSocket realtime progress
  useWebSocket();

  // Sync sidebar media type → content filter
  useEffect(() => {
    setContentFilter(storeMediaTab);
  }, [storeMediaTab]);

  // ── Auth check ──
  useEffect(() => {
    const stored = localStorage.getItem("veo3_user");
    const token = localStorage.getItem("veo3_token");
    if (stored && token) {
      try {
        const parsed = JSON.parse(stored);
        setUser({ ...parsed, token });
      } catch {
        localStorage.removeItem("veo3_user");
        localStorage.removeItem("veo3_token");
        router.push("/login");
      }
    } else {
      router.push("/login");
    }
    // Load grid preference
    const savedGrid = localStorage.getItem("veo3_home_grid");
    if (savedGrid) setGridCols(parseInt(savedGrid));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setOnRefreshHistory = useStore((s) => s.setOnRefreshHistory);

  // ── Fetch history ──
  const fetchHistory = useCallback(async () => {
    try {
      const data = await api.getJobs(120);
      const jobs = data.jobs || [];
      setHistory(jobs);
      setIsLoadingHistory(false);

      // Restore active jobs from API (survive page reload)
      // Only restore jobs from the last 15 minutes
      const store = useStore.getState();
      const fifteenMinAgo = Date.now() - 15 * 60 * 1000;
      for (const job of jobs) {
        if (["queued", "pending", "processing"].includes(job.status)) {
          const jobStarted = job.started_at ? new Date(job.started_at).getTime() : 0;
          if (jobStarted > fifteenMinAgo && !store.activeJobs.has(job.id)) {
            store.addActiveJob({
              id: job.id,
              prompt: job.prompt || "",
              status: job.status,
              progress: job.progress_percent || 0,
              mediaType: job.media_type || "video",
              startedAt: jobStarted || Date.now(),
            });
          }
        }
      }
    } catch {
      setIsLoadingHistory(false);
    }
  }, [setHistory]);

  useEffect(() => {
    if (user) {
      fetchHistory();
      setOnRefreshHistory(fetchHistory);
    }
    return () => setOnRefreshHistory(null);
  }, [user, fetchHistory, setOnRefreshHistory]);

  // Poll khi co active jobs — fallback when WS fails
  useEffect(() => {
    if (activeJobs.size === 0) return;
    const interval = setInterval(async () => {
      await fetchHistory();
      // Detect stuck/failed/completed jobs from API data
      const freshData = useStore.getState().history;
      activeJobs.forEach((job, jobId) => {
        const apiJob = freshData.find((h: { id: number }) => h.id === jobId);
        if (apiJob) {
          if (apiJob.status === "completed") {
            const mediaLabel = (apiJob.media_type || "video") === "image" ? "Ảnh" : "Video";
            useStore.getState().updateActiveJob(jobId, {
              progress: 100, status: "completed", videoUrl: apiJob.video_url || apiJob.r2_url,
            });
            useStore.getState().showToast(`🎉 ${mediaLabel} đã tạo xong!`, "success");
            setTimeout(() => useStore.getState().removeActiveJob(jobId), 2000);
          } else if (apiJob.status === "failed") {
            useStore.getState().updateActiveJob(jobId, {
              status: "failed", error: apiJob.error || "Thất bại",
            });
            useStore.getState().showToast(`❌ ${apiJob.error || "Tạo thất bại"}`, "error");
            setTimeout(() => useStore.getState().removeActiveJob(jobId), 3000);
          } else if (apiJob.progress_percent) {
            useStore.getState().updateActiveJob(jobId, {
              progress: apiJob.progress_percent, status: apiJob.status,
            });
          }
        }
      });
    }, 5000);
    return () => clearInterval(interval);
  }, [activeJobs.size, fetchHistory]);

  const handleGridChange = (cols: number) => {
    setGridCols(cols);
    localStorage.setItem("veo3_home_grid", String(cols));
  };

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg-primary)" }}>
        <div className="spinner spinner-lg"></div>
      </div>
    );
  }


  const completedJobs = history.filter((j) => {
    if (j.status !== "completed") return false;
    if (contentFilter === "all") return true;
    const mt = j.media_type || "video";
    return mt === contentFilter;
  });
  const activeJobList = Array.from(activeJobs.values());

  // Count by type
  const allCompleted = history.filter((j) => j.status === "completed");
  const videoCount = allCompleted.filter((j) => (j.media_type || "video") === "video").length;
  const imageCount = allCompleted.filter((j) => (j.media_type || "video") === "image").length;

  // Dynamic grid class
  const gridClass = {
    2: "grid-cols-1 sm:grid-cols-2",
    3: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
    4: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4",
    6: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6",
    8: "grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8",
  }[gridCols] || "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4";

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Toast />
      <Navbar />

      <main style={{ paddingTop: 72, paddingLeft: 20, paddingRight: 20, paddingBottom: 20 }}>
        {/* ═══ TWO-COLUMN LAYOUT: Settings LEFT + Content RIGHT ═══ */}
        <div className="flex gap-6">
          {/* ── LEFT: Settings Panel (fixed sidebar) ── */}
          <div className="w-[295px] shrink-0 hidden lg:block">
            <SettingsPanel />
          </div>

          {/* ── RIGHT: Main content area (tối hơn sidebar để tạo tương phản) ── */}
          <div className="flex-1 min-w-0 rounded-2xl flex flex-col" style={{
            background: "var(--bg-content)",
            border: "1px solid var(--border-subtle)",
            minHeight: "calc(100vh - 92px)",
          }}>
            {/* Scrollable content */}
            <div className="flex-1 p-5">
              {/* Active Jobs — filtered by content tab */}
              {(() => {
                const filteredActive = contentFilter === "all"
                  ? activeJobList
                  : activeJobList.filter((j) => (j.mediaType || "video") === contentFilter);
                if (filteredActive.length === 0) return null;
                return (
                  <div className="mb-6">
                    <div className="flex items-center gap-2 mb-4">
                      <span className="pulse-dot"></span>
                      <h2 className="text-sm font-semibold" style={{ color: "var(--text-muted)" }}>
                        Đang xử lý ({filteredActive.length})
                      </h2>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {filteredActive.map((job) => (
                        <ActiveJobCard key={job.id} job={job} />
                      ))}
                    </div>
                  </div>
                );
              })()}

              {/* Grid Mode selector + Media Tabs + header */}
              {allCompleted.length > 0 && (
                <div className="pb-6">
                  <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
                    {/* Media type tabs */}
                    <div className="flex items-center gap-1 p-0.5 rounded-lg" style={{ background: "var(--bg-tertiary)" }}>
                      {([
                        { key: "all" as const, label: "Tất cả", count: allCompleted.length, icon: "apps" },
                        { key: "video" as const, label: "Video", count: videoCount, icon: "movie" },
                        { key: "image" as const, label: "Ảnh", count: imageCount, icon: "image" },
                      ]).map((tab) => (
                        <button
                          key={tab.key}
                          onClick={() => setContentFilter(tab.key)}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all"
                          style={{
                            background: contentFilter === tab.key ? "var(--neon-blue)" : "transparent",
                            color: contentFilter === tab.key ? "white" : "var(--text-muted)",
                          }}
                        >
                          <span className="material-symbols-rounded" style={{ fontSize: 14 }}>{tab.icon}</span>
                          {tab.label}
                          <span className="opacity-60">({tab.count})</span>
                        </button>
                      ))}
                    </div>

                    <div className="flex items-center gap-3">
                      {/* Grid mode — icon popup */}
                      <div className="relative">
                        <button
                          onClick={() => setShowGridPopup(!showGridPopup)}
                          className="p-1.5 rounded-lg transition-all"
                          title="Chế độ hiển thị"
                          style={{
                            background: showGridPopup ? "var(--neon-blue)" : "var(--bg-tertiary)",
                            color: showGridPopup ? "white" : "var(--text-muted)",
                            border: "1px solid var(--border-subtle)",
                          }}
                        >
                          <span className="material-symbols-rounded text-sm">grid_view</span>
                        </button>

                        {showGridPopup && (
                          <>
                            <div className="fixed inset-0 z-40" onClick={() => setShowGridPopup(false)} />
                            <div className="absolute right-0 top-full mt-1 z-50 rounded-lg p-1 flex gap-0.5" style={{
                              background: "var(--bg-card-solid)",
                              border: "1px solid var(--border-medium)",
                              boxShadow: "var(--shadow-dropdown)",
                            }}>
                              {GRID_MODES.map((mode) => (
                                <button
                                  key={mode.cols}
                                  onClick={() => { handleGridChange(mode.cols); setShowGridPopup(false); }}
                                  className="px-2 py-1.5 rounded-md transition-all"
                                  title={mode.label}
                                  style={{
                                    background: gridCols === mode.cols ? "var(--neon-blue)" : "transparent",
                                    color: gridCols === mode.cols ? "white" : "var(--text-muted)",
                                  }}
                                >
                                  <span className="material-symbols-rounded text-sm">{mode.icon}</span>
                                </button>
                              ))}
                            </div>
                          </>
                        )}
                      </div>

                      <button onClick={() => router.push("/videos")} className="btn-ghost !text-xs flex items-center gap-1"
                        style={{ color: "var(--neon-blue)" }}>
                        Xem tất cả
                        <span className="material-symbols-rounded text-sm">arrow_forward</span>
                      </button>

                      {/* Select All / Batch Actions */}
                      <button
                        onClick={() => {
                          if (selectedIds.size === completedJobs.length) {
                            setSelectedIds(new Set());
                          } else {
                            setSelectedIds(new Set(completedJobs.map(j => j.id)));
                          }
                        }}
                        className="p-1.5 rounded-lg transition-all"
                        title={selectedIds.size === completedJobs.length ? "Bỏ chọn tất cả" : "Chọn tất cả"}
                        style={{
                          background: selectedIds.size > 0 ? "var(--neon-blue)" : "var(--bg-tertiary)",
                          color: selectedIds.size > 0 ? "white" : "var(--text-muted)",
                          border: "1px solid var(--border-subtle)",
                        }}
                      >
                        <span className="material-symbols-rounded text-sm">
                          {selectedIds.size === completedJobs.length && selectedIds.size > 0 ? "deselect" : "select_all"}
                        </span>
                      </button>

                      {/* Batch Download */}
                      {selectedIds.size > 0 && (
                        <>
                          <button
                            onClick={async () => {
                              const selected = completedJobs.filter(j => selectedIds.has(j.id));
                              const showToast = useStore.getState().showToast;
                              showToast(`⏳ Đang tải ${selected.length} file...`, "info");
                              for (const job of selected) {
                                const url = job.video_url || job.r2_url;
                                if (!url) continue;
                                try {
                                  const isImg = job.media_type === "image";
                                  if (isImg) {
                                    const resp = await fetch(url);
                                    const blob = await resp.blob();
                                    const ext = blob.type.includes("png") ? "png" : "jpg";
                                    const a = document.createElement("a");
                                    a.href = URL.createObjectURL(blob);
                                    a.download = `${isImg ? "image" : "video"}-${job.id}.${ext}`;
                                    document.body.appendChild(a);
                                    a.click();
                                    document.body.removeChild(a);
                                    URL.revokeObjectURL(a.href);
                                  } else {
                                    const dlUrl = api.getDownloadUrl(job.id, "720");
                                    const a = document.createElement("a");
                                    a.href = dlUrl;
                                    a.download = `video-${job.id}.mp4`;
                                    document.body.appendChild(a);
                                    a.click();
                                    document.body.removeChild(a);
                                  }
                                  await new Promise(r => setTimeout(r, 500));
                                } catch (_e) { }
                              }
                              showToast(`✅ Đã tải ${selected.length} file!`, "success");
                              setSelectedIds(new Set());
                            }}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                            style={{
                              background: "var(--success)",
                              color: "white",
                            }}
                          >
                            <span className="material-symbols-rounded" style={{ fontSize: 14 }}>download</span>
                            Tải {selectedIds.size} file
                          </button>

                          {/* Batch Delete */}
                          <button
                            onClick={async () => {
                              if (!confirm(`Xóa ${selectedIds.size} mục đã chọn?`)) return;
                              const showToast = useStore.getState().showToast;
                              const removeJob = useStore.getState().removeJob;
                              let deleted = 0;
                              let failed = 0;
                              for (const id of selectedIds) {
                                try {
                                  await api.deleteJob(id);
                                  removeJob(id);
                                  deleted++;
                                } catch { failed++; }
                              }
                              setSelectedIds(new Set());
                              if (deleted > 0) showToast(`🗑️ Đã xóa ${deleted} mục!`, "success");
                              if (failed > 0) showToast(`⚠️ ${failed} mục không xóa được (đang xử lý?)`, "error");
                            }}
                            className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
                            style={{
                              background: "var(--error)",
                              color: "white",
                            }}
                          >
                            <span className="material-symbols-rounded" style={{ fontSize: 14 }}>delete</span>
                            Xóa {selectedIds.size}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                  {completedJobs.length > 0 ? (
                    <div className={`grid ${gridClass} gap-4`}>
                      {completedJobs.slice(0, 60).map((job) => (
                        <VideoCard key={job.id} job={job} compact={gridCols >= 6} selectable selected={selectedIds.has(job.id)} onToggleSelect={toggleSelect} />
                      ))}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center py-10">
                      <span className="material-symbols-rounded text-4xl mb-3" style={{ color: "var(--text-muted)" }}>
                        {contentFilter === "video" ? "movie" : contentFilter === "image" ? "image" : "inbox"}
                      </span>
                      <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                        {contentFilter === "video" ? "Chưa có video nào" : contentFilter === "image" ? "Chưa có ảnh nào" : "Chưa có nội dung"}
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* Loading skeleton */}
              {isLoadingHistory && allCompleted.length === 0 && (
                <div className={`grid ${gridClass} gap-4`}>
                  {Array.from({ length: 6 }).map((_, i) => (
                    <div key={i} className="video-card fade-in">
                      <div className="aspect-video shimmer" />
                      <div className="p-3">
                        <div className="h-4 w-3/4 shimmer rounded" />
                        <div className="h-3 w-1/2 shimmer rounded mt-2" />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Empty state — no content at all */}
              {!isLoadingHistory && allCompleted.length === 0 && activeJobList.length === 0 && (
                <div className="flex flex-col items-center py-16">
                  <span className="material-symbols-rounded text-6xl mb-4" style={{ color: "var(--text-muted)" }}>movie_creation</span>
                  <h2 className="text-xl font-bold mb-2" style={{ color: "var(--text-secondary)" }}>
                    Chưa có nội dung nào
                  </h2>
                  <p className="text-sm" style={{ color: "var(--text-muted)" }}>
                    Nhập prompt bên dưới và bấm Generate để bắt đầu!
                  </p>
                </div>
              )}
            </div>

            {/* ═══ PROMPT BOX — sticky bottom, no outer card ═══ */}
            <div className="sticky bottom-0 px-8 py-3" style={{
              background: "transparent",
            }}>
              <PromptBox onRefreshHistory={fetchHistory} />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
