/**
 * SettingsPanel — LEFT sidebar settings (giống "CẤU HÌNH CHUNG" trong ảnh mẫu)
 * Contains:
 *   - Image/Video mode toggle
 *   - Model selection dropdown
 *   - Aspect ratio dropdown
 *   - Number of outputs (1-4)
 *   - Delay giữa các task
 *   - Auto download toggle
 *   - Queue slot counter (X/8)
 *   - Account info
 */
"use client";
import { useState, useEffect, useCallback } from "react";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import { VIDEO_MODELS, IMAGE_MODELS, VIDEO_ASPECTS, IMAGE_ASPECTS } from "./PromptBox";

export function SettingsPanel() {
  const mediaTab = useStore((s) => s.mediaTab);
  const setMediaTab = useStore((s) => s.setMediaTab);
  const aspectRatio = useStore((s) => s.aspectRatio);
  const setAspectRatio = useStore((s) => s.setAspectRatio);
  const videoModel = useStore((s) => s.videoModel);
  const setVideoModel = useStore((s) => s.setVideoModel);
  const numberOfOutputs = useStore((s) => s.numberOfOutputs);
  const setNumberOfOutputs = useStore((s) => s.setNumberOfOutputs);
  const user = useStore((s) => s.user);
  const activeJobs = useStore((s) => s.activeJobs);

  const imageModel = useStore((s) => s.imageModel);
  const setImageModel = useStore((s) => s.setImageModel);
  const [delay, setDelay] = useState(0);
  const [autoDownload, setAutoDownload] = useState(false);
  const [outputPath, setOutputPath] = useState(() => {
    if (typeof window !== 'undefined') return localStorage.getItem('veo3_output_path') || '';
    return '';
  });
  const [autoUpscale, setAutoUpscale] = useState(() => {
    if (typeof window !== 'undefined') return localStorage.getItem('veo3_auto_upscale') || 'none';
    return 'none';
  });
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [show4kTooltip, setShow4kTooltip] = useState(false);
  const [queueStatus, setQueueStatus] = useState<{ active: number; max: number; waiting: number }>({ active: 0, max: 8, waiting: 0 });

  const isVideo = mediaTab === "video";
  const currentModels = isVideo ? VIDEO_MODELS : IMAGE_MODELS;
  const currentAspects = isVideo ? VIDEO_ASPECTS : IMAGE_ASPECTS;
  const currentModelKey = isVideo ? videoModel : imageModel;
  const currentModel = currentModels.find((m) => m.key === currentModelKey) || currentModels[0];
  const totalCost = currentModel.price * numberOfOutputs;
  const totalCredits = currentModel.credits * numberOfOutputs;

  const handleModelChange = (key: string) => {
    if (isVideo) setVideoModel(key);
    else setImageModel(key);
  };

  // Fetch queue status
  const fetchQueue = useCallback(async () => {
    try {
      const data = await api.getQueueStatus();
      setQueueStatus(data as any);
    } catch {}
  }, []);

  useEffect(() => {
    if (user) fetchQueue();
  }, [user, fetchQueue]);

  // Always poll queue status to keep slot counter accurate
  useEffect(() => {
    if (!user) return;
    const interval = setInterval(fetchQueue, 5000);
    return () => clearInterval(interval);
  }, [user, fetchQueue]);
  // Separate slot counts by media type
  const activeJobsArray = Array.from(activeJobs.values());
  const videoActive = activeJobsArray.filter((j) => (j.mediaType || "video") === "video").length;
  const imageActive = activeJobsArray.filter((j) => (j.mediaType || "video") === "image").length;
  const maxSlots = isVideo ? 8 : 10;
  const currentActive = isVideo ? videoActive : imageActive;

  const slotColor = currentActive >= maxSlots ? "var(--error)" :
                    currentActive >= maxSlots - 2 ? "var(--warning)" : "var(--success)";

  return (
    <div className="p-4 space-y-5 h-fit sticky top-20 rounded-2xl" style={{
      minWidth: "265px",
      background: "var(--bg-card-solid)",
      border: "1px solid var(--border-subtle)",
      boxShadow: "var(--shadow-elevated)",
    }}>
      {/* ═══ Title ═══ */}
      <div className="flex items-center gap-2 pb-3" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
        <span className="material-symbols-rounded text-lg" style={{ color: "var(--neon-purple)" }}>tune</span>
        <h2 className="text-sm font-bold uppercase tracking-wider" style={{ color: "var(--text-primary)" }}>
          Cấu hình chung
        </h2>
      </div>

      {/* ═══ Image / Video Mode ═══ */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
          Loại nội dung:
        </label>
        <div className="flex rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
          <button
            onClick={() => {
              setMediaTab("image");
              if (!IMAGE_ASPECTS.find(a => a.value === aspectRatio)) setAspectRatio("16:9");
            }}
            className="flex-1 flex items-center justify-center gap-1.5 py-2 text-xs font-medium transition-all"
            style={{
              background: !isVideo ? "var(--neon-blue)" : "transparent",
              color: !isVideo ? "white" : "var(--text-muted)",
            }}
          >
            <span className="material-symbols-rounded text-sm">image</span>
            Hình ảnh
          </button>
          <button
            onClick={() => {
              setMediaTab("video");
              if (!VIDEO_ASPECTS.find(a => a.value === aspectRatio)) setAspectRatio("16:9");
            }}
            className="flex-1 flex items-center justify-center gap-1.5 py-2 text-xs font-medium transition-all"
            style={{
              background: isVideo ? "var(--neon-blue)" : "transparent",
              color: isVideo ? "white" : "var(--text-muted)",
            }}
          >
            <span className="material-symbols-rounded text-sm">videocam</span>
            Video
          </button>
        </div>
      </div>

      {/* ═══ Model ═══ */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
          Model:
        </label>
        {isVideo ? (
          <div className="input-field !py-2 !text-sm flex items-center gap-2"
            style={{ background: "var(--bg-input)" }}>
            <span>🎬</span>
            <span style={{ color: "var(--text-primary)" }}>Veo 3.1 - Quality</span>
          </div>
        ) : (
          <select
            value={imageModel}
            onChange={(e) => setImageModel(e.target.value)}
            className="input-field !py-2 !text-sm cursor-pointer"
            style={{ background: "var(--bg-input)" }}
          >
            {IMAGE_MODELS.map((m) => (
              <option key={m.key} value={m.key}>
                {m.icon} {m.label}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* ═══ Tỷ lệ (Aspect Ratio) ═══ */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
          Tỷ lệ:
        </label>
        <select
          value={aspectRatio}
          onChange={(e) => setAspectRatio(e.target.value)}
          className="input-field !py-2 !text-sm cursor-pointer"
          style={{ background: "var(--bg-input)" }}
        >
          {currentAspects.map((ar) => (
            <option key={ar.value} value={ar.value}>
              {ar.label}
            </option>
          ))}
        </select>
      </div>

      {/* ═══ Delay giữa các task ═══ */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
          Delay giữa các task (s):
        </label>
        <input
          type="number"
          min={0}
          max={60}
          value={delay}
          onChange={(e) => setDelay(Number(e.target.value))}
          className="input-field !py-2 !text-sm"
          style={{ background: "var(--bg-input)" }}
        />
      </div>

      {/* ═══ Số ô kết quả ═══ */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
          Số ô kết quả (1-3):
        </label>
        <div className="grid grid-cols-3 gap-1.5">
          {[1, 2, 3].map((n) => (
            <button
              key={n}
              onClick={() => setNumberOfOutputs(n)}
              className={`chip !px-0 !py-2 text-sm ${numberOfOutputs === n ? "chip-active" : ""}`}
            >
              x{n}
            </button>
          ))}
        </div>
      </div>



      {/* ═══ Slot Counter (X/8) ═══ */}
      <div className="rounded-lg p-3" style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border-subtle)" }}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Số lượng {isVideo ? "Video" : "Ảnh"}
          </span>
          <span className="text-sm font-bold font-mono" style={{ color: slotColor }}>
            {currentActive}/{maxSlots}
          </span>
        </div>
        <div className="w-full h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-primary)" }}>
          <div className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${(currentActive / maxSlots) * 100}%`,
              background: slotColor,
            }}
          />
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-xs font-semibold" style={{ color: "#f59e0b" }}>
            Hàng chờ:
          </span>
          <span className="text-xs font-bold font-mono" style={{ color: "#f59e0b" }}>
            {queueStatus.waiting}
          </span>
        </div>
      </div>

      {/* ═══ Output Folder ═══ */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
          📁 Thư mục tải xuống:
        </label>
        <input
          type="text"
          value={outputPath}
          onChange={(e) => {
            setOutputPath(e.target.value);
            localStorage.setItem('veo3_output_path', e.target.value);
          }}
          placeholder="C:\Users\...\Downloads"
          className="input-field !py-2 !text-sm"
          style={{ background: "var(--bg-input)" }}
        />
        <p className="text-[10px] mt-1" style={{ color: "var(--text-muted)" }}>
          Đường dẫn lưu file khi auto tải xuống
        </p>
      </div>

      {/* ═══ Separator ═══ */}
      <div style={{ borderTop: "1px solid var(--border-subtle)" }} />

      {/* ═══ Account info ═══ */}
      {user && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>Tài khoản:</span>
            <span className="text-xs font-bold" style={{ color: "var(--neon-blue)" }}>{user.username}</span>
            <span className="text-xs" style={{ color: "var(--success)" }}>🟢</span>
          </div>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>
            Số dư: <span className="font-bold" style={{ color: "var(--neon-purple)" }}>{user.balance.toLocaleString()} credits</span>
          </div>
        </div>
      )}

      {/* ═══ Cost Summary ═══ */}
      <div className="rounded-lg p-3" style={{ background: "var(--gradient-glow)", border: "1px solid var(--border-subtle)" }}>
        <div className="flex items-center justify-between text-xs">
          <span style={{ color: "var(--text-muted)" }}>Chi phí/lần tạo:</span>
          <span className="font-bold" style={{ color: "var(--neon-blue)" }}>{totalCredits.toLocaleString()} credits</span>
        </div>
      </div>

      {/* ═══ Advanced Settings (popup) ═══ */}
      <div className="relative">
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="w-full flex items-center justify-center gap-1.5 text-xs font-semibold uppercase tracking-wider py-2 rounded-lg transition-all"
          style={{
            color: showAdvanced ? "var(--neon-blue)" : "var(--text-muted)",
            background: showAdvanced ? "rgba(79,70,229,0.08)" : "transparent",
          }}
        >
          <span className="material-symbols-rounded text-sm">download</span>
          Cài đặt tải xuống tự động
        </button>

        {showAdvanced && (
          <>
            {/* Backdrop */}
            <div className="fixed inset-0 z-40" onClick={() => setShowAdvanced(false)} />

            {/* Popup */}
            <div className="absolute left-0 right-0 bottom-full mb-2 z-50 rounded-xl p-4 space-y-4" style={{
              background: "var(--bg-card-solid)",
              border: "1px solid var(--border-medium)",
              boxShadow: "var(--shadow-dropdown)",
            }}>
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wider" style={{ color: "var(--text-primary)" }}>
                  ⬇️ Cài đặt tải xuống tự động
                </h3>
                <button onClick={() => setShowAdvanced(false)} className="p-0.5 rounded-md hover:opacity-70">
                  <span className="material-symbols-rounded text-sm" style={{ color: "var(--text-muted)" }}>close</span>
                </button>
              </div>

              {/* Output path */}
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
                  Đường dẫn tải xuống:
                </label>
                <input
                  type="text"
                  value={outputPath}
                  onChange={(e) => {
                    setOutputPath(e.target.value);
                    localStorage.setItem('veo3_output_path', e.target.value);
                  }}
                  placeholder="D:\\Videos\\Veo3"
                  className="input-field !text-xs"
                />
              </div>

              {/* Auto upscale */}
              <div>
                <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
                  Auto Upscale khi tải:
                </label>
                <div className="flex gap-1.5">
                  {[
                    { key: "none", label: "Tắt", locked: false },
                    { key: "1080p", label: "1080p", locked: false },
                    { key: "4k", label: "4K", locked: true },
                  ].map((opt) => (
                    <button
                      key={opt.key}
                      onClick={() => {
                        if (opt.locked) {
                          setShow4kTooltip(true);
                          setTimeout(() => setShow4kTooltip(false), 2000);
                          return;
                        }
                        setAutoUpscale(opt.key);
                        localStorage.setItem('veo3_auto_upscale', opt.key);
                      }}
                      className="flex-1 py-1.5 rounded-lg text-xs font-medium transition-all relative flex items-center justify-center gap-1"
                      style={{
                        background: opt.locked ? "var(--bg-tertiary)" : (autoUpscale === opt.key ? "var(--neon-blue)" : "var(--bg-tertiary)"),
                        color: opt.locked ? "var(--text-muted)" : (autoUpscale === opt.key ? "white" : "var(--text-secondary)"),
                        border: `1px solid ${opt.locked ? "var(--border-subtle)" : (autoUpscale === opt.key ? "var(--neon-blue)" : "var(--border-subtle)")}`,
                        opacity: opt.locked ? 0.6 : 1,
                        textDecoration: opt.locked ? "line-through" : "none",
                      }}
                    >
                      {opt.locked && <span className="material-symbols-rounded" style={{ fontSize: "12px" }}>lock</span>}
                      {opt.label}
                    </button>
                  ))}
                </div>
                {show4kTooltip && (
                  <p className="text-[10px] mt-1.5 text-center font-medium" style={{ color: "var(--neon-purple)" }}>
                    🔒 Sắp ra mắt
                  </p>
                )}
              </div>

              {/* Confirm button */}
              <button
                onClick={() => setShowAdvanced(false)}
                className="w-full py-2 rounded-lg text-xs font-bold transition-all"
                style={{
                  background: "var(--neon-blue)",
                  color: "white",
                  border: "none",
                }}
              >
                ✓ Xác nhận
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
