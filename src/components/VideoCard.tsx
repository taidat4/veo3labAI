/**
 * VideoCard — Media card cho trang chủ + My Videos grid
 * Supports both VIDEO and IMAGE media types
 * Click → mở VideoPreviewModal
 */
"use client";
import { useState, useRef, useEffect } from "react";
import { useStore, type HistoryJob } from "@/lib/store";
import { api, API_BASE } from "@/lib/api";
import { VideoPreviewModal } from "./VideoPreviewModal";

export function VideoCard({ job, compact = false, selectable = false, selected = false, onToggleSelect }: {
  job: HistoryJob;
  compact?: boolean;
  selectable?: boolean;
  selected?: boolean;
  onToggleSelect?: (id: number) => void;
}) {
  const [hovering, setHovering] = useState(false);
  const [showMenu, setShowMenu] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const showToast = useStore((s) => s.showToast);
  const upscalingJobIds = useStore((s) => s.upscalingJobIds);
  const addUpscalingJob = useStore((s) => s.addUpscalingJob);
  const removeUpscalingJob = useStore((s) => s.removeUpscalingJob);
  const updateHistoryJob = useStore((s) => s.updateHistoryJob);

  const removeJob = useStore((s) => s.removeJob);
  const mediaUrl = job.video_url || job.r2_url;
  const isImage = job.media_type === "image";
  // Upscale state: combine global store + server-persisted
  const upscaling = upscalingJobIds.has(job.id);
  const isUpscaling = upscaling || job.upscale_status === "processing";
  const hasUpscaleUrl = !!job.upscale_url;

  // ★ Auto-resume poll on mount if backend says job is still processing
  useEffect(() => {
    if (job.upscale_status !== "processing" || upscaling) return;
    // Backend says processing but no active poll → resume
    addUpscalingJob(job.id);
    let pollCount = 0;
    const MAX_POLLS = 45; // ~6 phút (8s × 45)
    const pollInterval = setInterval(async () => {
      pollCount++;
      if (pollCount > MAX_POLLS) {
        clearInterval(pollInterval);
        removeUpscalingJob(job.id);
        updateHistoryJob(job.id, { upscale_status: undefined });
        showToast("⏰ Upscale timeout — thử lại sau", "error");
        return;
      }
      try {
        const st = await api.getUpscaleStatus(job.id);
        if (st.status === "completed" && st.upscale_url) {
          clearInterval(pollInterval);
          removeUpscalingJob(job.id);
          updateHistoryJob(job.id, { upscale_status: "completed", upscale_url: st.upscale_url });
          showToast("✅ Upscale hoàn tất!", "success");
        } else if (st.status === "not_started" && !st.upscale_error) {
          clearInterval(pollInterval);
          removeUpscalingJob(job.id);
        } else if (st.status === "not_started" && st.upscale_error) {
          clearInterval(pollInterval);
          removeUpscalingJob(job.id);
          updateHistoryJob(job.id, { upscale_status: undefined });
          showToast(`❌ ${st.upscale_error}`, "error");
        }
      } catch {
        clearInterval(pollInterval);
        removeUpscalingJob(job.id);
      }
    }, 8000);
    return () => clearInterval(pollInterval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id, job.upscale_status]);

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm("Xóa video/ảnh này?")) return;
    try {
      await api.deleteJob(job.id);
      removeJob(job.id);
      showToast("🗑️ Đã xóa!", "success");
    } catch (err: any) {
      showToast(`❌ ${err?.message || "Không thể xóa"}`, "error");
    }
  };

  const handleMouseEnter = () => {
    setHovering(true);
    if (!isImage && videoRef.current && mediaUrl) {
      videoRef.current.play().catch(() => { });
    }
  };

  const handleMouseLeave = () => {
    setHovering(false);
    if (!isImage && videoRef.current) {
      videoRef.current.pause();
      videoRef.current.currentTime = 0;
    }
  };

  const handleDownload = async (quality: string) => {
    setShowMenu(false);

    if (isImage) {
      // Image: original or upscale
      if (!mediaUrl) return;

      // Upscale resolutions
      const resMap: Record<string, string> = {
        "1k": "RESOLUTION_1K",
        "2k": "RESOLUTION_2K",
        "4k": "RESOLUTION_4K",
      };

      if (resMap[quality]) {
        try {
          addUpscalingJob(job.id);
          showToast(`⏳ Đang upscale ảnh lên ${quality.toUpperCase()}...`, "info");
          const resp = await api.upscaleImage(job.id, resMap[quality]);
          if (resp.success && resp.upscale_url) {
            const a = document.createElement("a");
            a.href = resp.upscale_url;
            a.download = `image-${job.id}-${quality}.png`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            showToast(`✅ Đã tải ảnh ${quality.toUpperCase()}!`, "success");
            removeUpscalingJob(job.id);
            return;
          }
          removeUpscalingJob(job.id);
          showToast("❌ Upscale ảnh thất bại", "error");
        } catch (_e) {
          removeUpscalingJob(job.id);
          showToast("❌ Lỗi upscale ảnh, tải ảnh gốc...", "error");
          // Fallback to original
        }
      }

      // Original download
      try {
        const resp = await fetch(mediaUrl);
        const blob = await resp.blob();
        const ext = blob.type.includes("png") ? "png" : "jpg";
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `image-${job.id}.${ext}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(a.href);
      } catch {
        showToast("❌ Lỗi tải ảnh", "error");
      }
      return;
    }

    // Video download
    if (quality === "1080") {
      // ★ If already upscaled → download directly!
      if (hasUpscaleUrl && job.upscale_url) {
        const dlUrl = job.upscale_url.startsWith("/") ? `${API_BASE}${job.upscale_url}` : job.upscale_url;
        showToast("⏳ Đang tải video 1080p...", "info");
        try {
          const resp = await fetch(dlUrl);
          const blob = await resp.blob();
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = `video-${job.id}-1080p.mp4`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(a.href);
          showToast("✅ Đã tải video 1080p!", "success");
        } catch {
          // Fallback: direct link
          const a = document.createElement("a");
          a.href = dlUrl;
          a.download = `video-${job.id}-1080p.mp4`;
          a.target = "_blank";
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
        }
        return;
      }
      try {
        addUpscalingJob(job.id);
        showToast("⏳ Đang upscale lên 1080p...", "info");
        const resp = await api.upscaleVideo(job.id);
        if (resp.status === "completed" && resp.upscale_url) {
          updateHistoryJob(job.id, { upscale_status: "completed", upscale_url: resp.upscale_url });
          removeUpscalingJob(job.id);
          showToast("✅ Upscale xong! Nhấn tải 1080p lần nữa để tải", "success");
          return;
        }
        if (resp.status === "processing") {
          showToast("⏳ Đang upscale 1080p (~1-3 phút)...", "info");
          // Poll for completion
          let retried = false;
          let pollCount2 = 0;
          const MAX_POLLS_2 = 45; // ~6 phút
          const pollInterval = setInterval(async () => {
            pollCount2++;
            if (pollCount2 > MAX_POLLS_2) {
              clearInterval(pollInterval);
              removeUpscalingJob(job.id);
              showToast("⏰ Upscale quá 6 phút — thử lại sau", "error");
              return;
            }
            try {
              const st = await api.getUpscaleStatus(job.id);
              if (st.status === "completed" && st.upscale_url) {
                clearInterval(pollInterval);
                removeUpscalingJob(job.id);
                // ★ Update store — KHÔNG auto-download, chỉ cập nhật badge
                updateHistoryJob(job.id, { upscale_status: "completed", upscale_url: st.upscale_url });
                showToast("✅ Upscale 1080p hoàn tất! Nhấn tải 1080p để tải video", "success");
              } else if (st.status === "not_started" && st.upscale_error) {
                // Upscale failed — auto-retry once
                if (!retried) {
                  retried = true;
                  showToast("⚠️ Upscale lỗi, đang thử lại...", "info");
                  try {
                    await api.upscaleVideo(job.id);
                  } catch { }
                  // Keep polling — the retry will create a new task
                } else {
                  // Already retried — give up
                  clearInterval(pollInterval);
                  removeUpscalingJob(job.id);
                  showToast(`❌ ${st.upscale_error} — nhấn tải 1080p để thử lại`, "error");
                }
              }
              // status === "processing" → keep polling, do nothing
            } catch (_e) {
              clearInterval(pollInterval);
              removeUpscalingJob(job.id);
              showToast("❌ Mất kết nối khi kiểm tra upscale", "error");
            }
          }, 8000);
          return;
        }
        removeUpscalingJob(job.id);
        showToast("⚠️ Upscale chưa sẵn sàng, thử lại sau", "info");
        return;
      } catch (err: any) {
        removeUpscalingJob(job.id);
        const errMsg = err?.message || "Lỗi không xác định";
        showToast(`❌ Upscale 1080p thất bại: ${errMsg}`, "error");
        return;
      }
    }
    const url = api.getDownloadUrl(job.id, quality);
    const a = document.createElement("a");
    a.href = url;
    a.download = `video-${job.id}-${quality}.mp4`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  if (job.status === "failed") {
    return (
      <div className="video-card p-4 fade-in">
        <div className="flex items-start gap-3">
          <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: "rgba(248, 113, 113, 0.1)" }}>
            <span className="material-symbols-rounded text-lg" style={{ color: "var(--error)" }}>error</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate" style={{ color: "var(--text-primary)" }}>{job.prompt}</p>
            <p className="text-xs mt-1" style={{ color: "var(--error)" }}>{job.error || "Thất bại"}</p>
            <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Đã hoàn {job.cost.toLocaleString()} credits</p>
          </div>
          <button onClick={handleDelete} className="btn-ghost !p-1.5 !rounded-lg shrink-0" title="Xóa"
            style={{ color: "var(--text-muted)" }}
            onMouseEnter={(e) => e.currentTarget.style.color = "var(--error)"}
            onMouseLeave={(e) => e.currentTarget.style.color = "var(--text-muted)"}>
            <span className="material-symbols-rounded text-lg">delete</span>
          </button>
        </div>
      </div>
    );
  }

  if (!mediaUrl) {
    return (
      <div className="video-card fade-in">
        <div className="aspect-video shimmer" />
        <div className="p-3">
          <div className="h-4 w-3/4 shimmer rounded" />
          <div className="h-3 w-1/2 shimmer rounded mt-2" />
        </div>
      </div>
    );
  }

  // Download options based on media type
  const downloadOptions = isImage
    ? [
      { val: "original", label: "Gốc", desc: "Nhanh" },
      { val: "1k", label: "1K", desc: "HD" },
      { val: "2k", label: "2K", desc: "Ultra HD" },
      { val: "4k", label: "4K", desc: "Max" },
    ]
    : [
      { val: "720", label: "720p", desc: "Nhanh" },
      { val: "1080", label: "1080p", desc: hasUpscaleUrl ? "✅ Sẵn sàng" : "HD", ready: hasUpscaleUrl },
    ];

  return (
    <>
      <div
        className="video-card fade-in group cursor-pointer"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onClick={() => setShowPreview(true)}
      >
        {/* Media thumbnail */}
        <div className="relative aspect-video bg-black overflow-hidden">
          {/* Selection checkbox */}
          {selectable && (
            <div className={`absolute top-2 left-2 z-10 transition-opacity ${hovering || selected ? 'opacity-100' : 'opacity-0'}`}>
              <button
                onClick={(e) => { e.stopPropagation(); onToggleSelect?.(job.id); }}
                className="w-6 h-6 rounded-md flex items-center justify-center transition-all"
                style={{
                  background: selected ? "var(--neon-blue)" : "rgba(255,255,255,0.2)",
                  backdropFilter: "blur(8px)",
                  border: selected ? "2px solid var(--neon-blue)" : "2px solid rgba(255,255,255,0.5)",
                }}
              >
                {selected && <span className="material-symbols-rounded text-white" style={{ fontSize: "16px" }}>check</span>}
              </button>
            </div>
          )}

          {/* Render image or video */}
          {isImage ? (
            <img
              src={mediaUrl}
              alt={job.prompt}
              className="w-full h-full object-cover"
              loading="lazy"
            />
          ) : (
            <video
              ref={videoRef}
              src={mediaUrl}
              className="w-full h-full object-cover"
              preload="metadata"
              muted
              loop
              playsInline
            />
          )}

          {/* Hover overlay */}
          <div className={`absolute inset-0 flex items-center justify-center bg-black/40 transition-opacity duration-200 ${hovering ? 'opacity-100' : 'opacity-0'}`}>
            <div className="flex items-center gap-2">
              <button className="w-12 h-12 rounded-full flex items-center justify-center transition-transform hover:scale-110"
                style={{ background: "rgba(255,255,255,0.15)", backdropFilter: "blur(8px)" }}
                onClick={(e) => { e.stopPropagation(); setShowPreview(true); }}>
                <span className="material-symbols-rounded text-2xl text-white">
                  {isImage ? "zoom_in" : "play_arrow"}
                </span>
              </button>
            </div>
          </div>

          {/* Quality/type badge + upscale indicator */}
          <div className="absolute top-2 right-2 flex items-center gap-1">
            {isUpscaling && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold animate-pulse"
                style={{ background: "rgba(168,85,247,0.9)", color: "white" }}>
                ⏳ Upscaling...
              </span>
            )}
            {hasUpscaleUrl && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold"
                style={{ background: "rgba(34,197,94,0.9)", color: "white" }}>
                ✅ HD
              </span>
            )}
            <span className="badge badge-neon !text-[10px]">
              {isImage ? "IMG" : "1080p"}
            </span>
          </div>

          {/* Duration — video only */}
          {!isImage && (
            <div className="absolute bottom-2 right-2 px-1.5 py-0.5 rounded text-[10px] font-medium"
              style={{ background: "rgba(0,0,0,0.7)", color: "white" }}>
              0:08
            </div>
          )}
        </div>

        {/* Info */}
        <div className="p-3">
          <p className="text-sm font-medium truncate mb-1.5" style={{ color: "var(--text-primary)" }}>{job.prompt}</p>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
              <span>{new Date(job.created_at).toLocaleDateString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" })}</span>
              <span>·</span>
              <span>{job.cost.toLocaleString()} credits</span>
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-0.5">
              {/* Delete button */}
              <button onClick={handleDelete} className="btn-ghost !p-1.5 !rounded-lg" title="Xóa"
                style={{ color: "var(--text-muted)" }}
                onMouseEnter={(e) => e.currentTarget.style.color = "var(--error)"}
                onMouseLeave={(e) => e.currentTarget.style.color = "var(--text-muted)"}>
                <span className="material-symbols-rounded text-lg">delete</span>
              </button>

              {/* Download dropdown */}
              <div className="relative">
                <button
                  onClick={(e) => { e.stopPropagation(); if (!isUpscaling) setShowMenu(!showMenu); }}
                  className="btn-ghost !p-1.5 !rounded-lg"
                  style={{ color: isUpscaling ? "var(--text-muted)" : "var(--neon-blue)", cursor: isUpscaling ? "not-allowed" : "pointer" }}
                  disabled={isUpscaling}
                >
                  <span className={`material-symbols-rounded text-lg ${isUpscaling ? "animate-spin" : ""}`}>
                    {isUpscaling ? "progress_activity" : "download"}
                  </span>
                </button>

                {showMenu && (
                  <div className="absolute right-0 bottom-full mb-1 rounded-xl overflow-hidden z-20 min-w-[150px]"
                    style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}>
                    {downloadOptions.map((q) => (
                      <button key={q.val}
                        onClick={(e) => { e.stopPropagation(); handleDownload(q.val); }}
                        className="w-full text-left px-4 py-2.5 flex items-center justify-between transition-colors text-sm"
                        style={{ color: (q as any).ready ? "#22c55e" : "var(--text-secondary)", fontWeight: (q as any).ready ? 600 : 400 }}
                        onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg-hover)"}
                        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                        <span>{q.label}</span>
                        <span className="text-xs" style={{ color: (q as any).ready ? "#22c55e" : (q as any).warn ? "var(--error)" : "var(--text-muted)" }}>
                          {q.desc}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Preview Modal */}
      {showPreview && (
        <VideoPreviewModal job={job} onClose={() => setShowPreview(false)} />
      )}
    </>
  );
}

