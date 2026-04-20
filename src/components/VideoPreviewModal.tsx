/**
 * VideoPreviewModal — Fullscreen media preview giống Google Flow
 * Supports both VIDEO and IMAGE
 */
"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { useStore, type HistoryJob } from "@/lib/store";

interface VideoPreviewModalProps {
  job: HistoryJob;
  onClose: () => void;
}

export function VideoPreviewModal({ job, onClose }: VideoPreviewModalProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(true);
  const [showDownloadMenu, setShowDownloadMenu] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [upscaleStatus, setUpscaleStatus] = useState<"idle" | "processing" | "done">("idle");
  const [upscaleMsg, setUpscaleMsg] = useState("");
  const showToast = useStore((s) => s.showToast);

  const mediaUrl = job.video_url || job.r2_url || "";
  const isImage = job.media_type === "image";

  // Auto-play on mount (video only)
  useEffect(() => {
    if (job.media_type !== "image" && videoRef.current) {
      videoRef.current.play().catch(() => { });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ESC to close
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === " " && !isImage) {
        e.preventDefault();
        togglePlay();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onClose]);

  // Prevent body scroll
  useEffect(() => {
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = ""; };
  }, []);

  const togglePlay = useCallback(() => {
    if (!videoRef.current) return;
    if (videoRef.current.paused) {
      videoRef.current.play().catch(() => { });
      setPlaying(true);
    } else {
      videoRef.current.pause();
      setPlaying(false);
    }
  }, []);

  const handleTimeUpdate = () => {
    if (videoRef.current) setCurrentTime(videoRef.current.currentTime);
  };

  const handleLoadedMetadata = () => {
    if (videoRef.current) setDuration(videoRef.current.duration);
  };

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!videoRef.current || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    videoRef.current.currentTime = pct * duration;
  };

  // ── Download handler ──
  const handleDownload = async (quality: string) => {
    setShowDownloadMenu(false);

    // Image download (original or upscale)
    if (isImage) {
      if (!mediaUrl) return;

      // Upscale resolutions
      const resMap: Record<string, string> = {
        "1k": "RESOLUTION_1K",
        "2k": "RESOLUTION_2K",
        "4k": "RESOLUTION_4K",
      };

      if (resMap[quality]) {
        try {
          showToast(`⏳ Đang upscale ảnh lên ${quality.toUpperCase()}...`, "info");
          const resp = await api.upscaleImage(job.id, resMap[quality]);
          if (resp.success && resp.upscale_url) {
            triggerFileDownload(resp.upscale_url, `image-${job.id}-${quality}.png`);
            showToast(`✅ Đã tải ảnh ${quality.toUpperCase()}!`, "success");
            return;
          }
          showToast("❌ Upscale ảnh thất bại", "error");
        } catch {
          showToast("❌ Lỗi upscale ảnh", "error");
        }
        return;
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
        showToast("⬇️ Đang tải ảnh...", "info");
      } catch {
        showToast("❌ Lỗi tải ảnh", "error");
      }
      return;
    }

    // Video download
    if (quality === "720") {
      const url = api.getDownloadUrl(job.id, "720");
      triggerFileDownload(url, `video-${job.id}-720p.mp4`);
      showToast("⬇️ Đang tải video 720p...", "info");
      return;
    }

    if (quality === "1080") {
      setUpscaleStatus("processing");
      setUpscaleMsg("Đang tăng độ phân giải video...");
      showToast("⏳ Đang upscale lên 1080p...", "info");
      try {
        const res = await api.triggerUpscale(job.id);
        if (res.status === "completed" && res.upscale_url) {
          setUpscaleStatus("done");
          setUpscaleMsg("");
          triggerFileDownload(res.upscale_url, `video-${job.id}-1080p.mp4`);
          showToast("✅ Đã tải video 1080p!", "success");
          return;
        }
        if (res.status === "processing") {
          setUpscaleMsg("Đang upscale... vui lòng đợi 1-3 phút");
          pollUpscale();
          return;
        }
        setUpscaleStatus("idle");
        setUpscaleMsg("");
        showToast("⚠️ Upscale chưa sẵn sàng, vui lòng thử lại sau", "info");
      } catch (err: any) {
        setUpscaleStatus("idle");
        setUpscaleMsg("");
        const errMsg = err?.message || "Lỗi không xác định";
        showToast(`❌ Upscale 1080p thất bại: ${errMsg}`, "error");
      }
      return;
    }
  };

  const pollUpscale = async () => {
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 5000));
      try {
        const res = await api.getUpscaleStatus(job.id);
        if (res.status === "completed" && res.upscale_url) {
          setUpscaleStatus("done");
          setUpscaleMsg("");
          triggerFileDownload(res.upscale_url, `video-${job.id}-1080p.mp4`);
          showToast("✅ Video 1080p đã sẵn sàng!", "success");
          return;
        }
      } catch { }
    }
    setUpscaleStatus("idle");
    setUpscaleMsg("");
    showToast("⚠️ Upscale timeout, vui lòng thử lại", "error");
  };

  const triggerFileDownload = (url: string, filename: string) => {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.target = "_blank";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const formatTime = (t: number) => {
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  // Model label
  const modelLabel = (() => {
    if (isImage) {
      const m: Record<string, string> = { NARWHAL: "Nano Banana 2", GEM_PIX_2: "Nano Banana Pro", IMAGEN_4: "Imagen 4" };
      return m[job.model_key || ""] || "Image";
    }
    const m: Record<string, string> = {
      veo31_fast_lp: "Veo 3.1 - Quality", veo_3_1_t2v_lite_low_priority: "Veo 3.1 - Quality",
      veo31_fast: "Veo 3.1 - Fast", veo31_lite: "Veo 3.1 - Lite", veo31_quality: "Veo 3.1 - Quality",
    };
    return m[job.model_key || ""] || "Veo 3.1 - Quality";
  })();

  return (
    <div className="fixed inset-0 z-[100] flex flex-col" style={{ background: "rgba(0,0,0,0.95)" }}>
      {/* ═══ TOP BAR ═══ */}
      <div className="flex items-center justify-between px-6 py-4 shrink-0">
        <div className="flex items-center gap-3 min-w-0">
          <button onClick={onClose}
            className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 transition-colors"
            style={{ background: "rgba(255,255,255,0.08)" }}
            onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.15)"}
            onMouseLeave={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.08)"}>
            <span className="material-symbols-rounded text-white text-xl">arrow_back</span>
          </button>
          <p className="text-white text-sm font-medium truncate max-w-[500px]">{job.prompt}</p>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <div className="relative">
            <button onClick={() => setShowDownloadMenu(!showDownloadMenu)}
              className="flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-colors"
              style={{ background: "rgba(255,255,255,0.1)", color: "white" }}
              onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.18)"}
              onMouseLeave={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.1)"}>
              <span className="material-symbols-rounded text-lg">download</span>
              Tải xuống
            </button>

            {showDownloadMenu && (
              <div className="absolute right-0 top-full mt-1 rounded-xl overflow-hidden z-50 min-w-[200px]"
                style={{ background: "#2a2a2a", border: "1px solid rgba(255,255,255,0.12)", boxShadow: "0 12px 40px rgba(0,0,0,0.6)" }}>
                {isImage ? (
                  <>
                    <button onClick={() => handleDownload("original")}
                      className="w-full text-left px-4 py-3 flex items-center justify-between transition-colors text-sm"
                      style={{ color: "rgba(255,255,255,0.9)" }}
                      onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.08)"}
                      onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                      <span className="font-medium">Gốc</span>
                      <span className="text-xs" style={{ color: "rgba(255,255,255,0.5)" }}>Nhanh</span>
                    </button>
                    {["1k", "2k", "4k"].map((res) => (
                      <button key={res} onClick={() => handleDownload(res)}
                        className="w-full text-left px-4 py-3 flex items-center justify-between transition-colors text-sm"
                        style={{ color: "rgba(255,255,255,0.9)" }}
                        onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.08)"}
                        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                        <span className="font-medium">{res.toUpperCase()}</span>
                        <span className="text-xs" style={{ color: "rgba(120,200,255,0.7)" }}>
                          {res === "1k" ? "HD" : res === "2k" ? "Ultra HD" : "Max"}
                        </span>
                      </button>
                    ))}
                  </>
                ) : (
                  <>
                    <button onClick={() => handleDownload("720")}
                      className="w-full text-left px-4 py-3 flex items-center justify-between transition-colors text-sm"
                      style={{ color: "rgba(255,255,255,0.9)" }}
                      onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.08)"}
                      onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                      <span className="font-medium">720p</span>
                      <span className="text-xs" style={{ color: "rgba(255,255,255,0.5)" }}>Gốc · Nhanh</span>
                    </button>
                    <button onClick={() => handleDownload("1080")}
                      disabled={upscaleStatus === "processing"}
                      className="w-full text-left px-4 py-3 flex items-center justify-between transition-colors text-sm"
                      style={{ color: "rgba(255,255,255,0.9)", opacity: upscaleStatus === "processing" ? 0.5 : 1 }}
                      onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.08)"}
                      onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                      <span className="font-medium">1080p HD</span>
                      <span className="text-xs" style={{ color: "rgba(120,200,255,0.7)" }}>
                        {upscaleStatus === "processing" ? "Đang xử lý..." : "Cần upscale ~2 phút"}
                      </span>
                    </button>
                  </>
                )}
              </div>
            )}
          </div>

          <button onClick={onClose}
            className="w-9 h-9 rounded-full flex items-center justify-center transition-colors"
            style={{ background: "rgba(255,255,255,0.08)" }}
            onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.15)"}
            onMouseLeave={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.08)"}>
            <span className="material-symbols-rounded text-white">close</span>
          </button>
        </div>
      </div>

      {/* ═══ UPSCALE BANNER ═══ */}
      {upscaleStatus === "processing" && (
        <div className="flex items-center gap-3 mx-6 mb-2 px-4 py-3 rounded-xl"
          style={{ background: "rgba(79,172,254,0.1)", border: "1px solid rgba(79,172,254,0.2)" }}>
          <div className="spinner !w-4 !h-4 !border-blue-400/30 !border-t-blue-400 shrink-0"></div>
          <span className="text-sm" style={{ color: "rgba(150,210,255,0.9)" }}>{upscaleMsg}</span>
        </div>
      )}

      {/* ═══ MEDIA AREA ═══ */}
      <div className="flex-1 flex items-center justify-center px-8 pb-4 min-h-0"
        onClick={(e) => { if (e.target === e.currentTarget && !isImage) togglePlay(); }}>
        <div className="relative flex items-center justify-center"
          style={{ maxWidth: "85vw", maxHeight: "75vh" }}>
          {isImage ? (
            <img
              src={mediaUrl}
              alt={job.prompt}
              className="rounded-xl object-contain"
              style={{ maxWidth: "85vw", maxHeight: "75vh", background: "#111" }}
            />
          ) : (
            <video
              ref={videoRef}
              src={mediaUrl}
              className="rounded-xl object-contain"
              style={{ maxWidth: "85vw", maxHeight: "75vh", background: "#000" }}
              loop
              playsInline
              onTimeUpdate={handleTimeUpdate}
              onLoadedMetadata={handleLoadedMetadata}
              onClick={togglePlay}
            />
          )}

          {/* Play/Pause overlay — video only */}
          {!isImage && !playing && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="w-16 h-16 rounded-full flex items-center justify-center"
                style={{ background: "rgba(0,0,0,0.5)", backdropFilter: "blur(8px)" }}>
                <span className="material-symbols-rounded text-3xl text-white">play_arrow</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ═══ BOTTOM CONTROLS ═══ */}
      <div className="shrink-0 px-8 pb-6">
        {/* Progress bar — video only */}
        {!isImage && (
          <div className="w-full max-w-[85vw] mx-auto h-1 rounded-full cursor-pointer group mb-4"
            style={{ background: "rgba(255,255,255,0.15)" }}
            onClick={handleSeek}>
            <div className="h-full rounded-full transition-all relative group-hover:h-1.5"
              style={{ width: `${progress}%`, background: "linear-gradient(90deg, var(--neon-blue), var(--neon-purple))" }}>
              <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 rounded-full opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ background: "white", boxShadow: "0 0 6px rgba(0,0,0,0.3)" }} />
            </div>
          </div>
        )}

        <div className="flex items-center justify-between max-w-[85vw] mx-auto">
          <div className="flex items-center gap-4">
            {!isImage && (
              <>
                <button onClick={togglePlay}
                  className="w-8 h-8 rounded-full flex items-center justify-center transition-colors"
                  style={{ background: "rgba(255,255,255,0.1)" }}>
                  <span className="material-symbols-rounded text-white text-lg">
                    {playing ? "pause" : "play_arrow"}
                  </span>
                </button>
                <span className="text-xs font-mono" style={{ color: "rgba(255,255,255,0.5)" }}>
                  {formatTime(currentTime)} / {formatTime(duration)}
                </span>
              </>
            )}
          </div>

          <span className="text-xs" style={{ color: "rgba(255,255,255,0.4)" }}>
            {modelLabel} · {new Date(job.created_at).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" })}
          </span>
        </div>
      </div>
    </div>
  );
}
