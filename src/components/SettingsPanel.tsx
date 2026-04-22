/**
 * SettingsPanel — LEFT sidebar settings
 * Contains:
 *   - Image/Video mode toggle
 *   - Khung hình / Thành phần sub-tabs (Video mode)
 *   - Model selection dropdown
 *   - Aspect ratio selector
 *   - Number of outputs (x1-x4)
 *   - Duration selector (4s/6s/8s)
 *   - Voice selector (Thành phần tab)
 *   - Queue slot counter
 *   - Account info
 */
"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import { VIDEO_MODELS, IMAGE_MODELS, VIDEO_ASPECTS, IMAGE_ASPECTS } from "./PromptBox";

// Voice list from Google Flow Labs
const VOICES = [
  { id: "achernar", name: "Achernar", desc: "Female, soft, high pitch", color: "#8b5cf6" },
  { id: "achird", name: "Achird", desc: "Male, friendly, mid pitch", color: "#6366f1" },
  { id: "algenib", name: "Algenib", desc: "Male, gravelly, low pitch", color: "#84cc16" },
  { id: "algieba", name: "Algieba", desc: "Male, easy-going, mid-low pitch", color: "#a3e635" },
  { id: "alnilam", name: "Alnilam", desc: "Male, firm, mid-low pitch", color: "#facc15" },
  { id: "canopus", name: "Canopus", desc: "Male, warm, mid pitch", color: "#fb923c" },
  { id: "capella", name: "Capella", desc: "Female, bright, high pitch", color: "#f472b6" },
  { id: "denali", name: "Denali", desc: "Male, deep, low pitch", color: "#22d3ee" },
  { id: "erinome", name: "Erinome", desc: "Female, calm, mid pitch", color: "#a78bfa" },
  { id: "fomalhaut", name: "Fomalhaut", desc: "Male, authoritative, mid pitch", color: "#34d399" },
];

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
  const videoSubTab = useStore((s) => s.videoSubTab);
  const setVideoSubTab = useStore((s) => s.setVideoSubTab);
  const videoDuration = useStore((s) => s.videoDuration);
  const setVideoDuration = useStore((s) => s.setVideoDuration);
  const selectedVoice = useStore((s) => s.selectedVoice);
  const setSelectedVoice = useStore((s) => s.setSelectedVoice);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [show4kTooltip, setShow4kTooltip] = useState(false);
  const [showVoicePanel, setShowVoicePanel] = useState(false);
  const [queueStatus, setQueueStatus] = useState<{ active: number; max: number; waiting: number }>({ active: 0, max: 8, waiting: 0 });
  const [creditCosts, setCreditCosts] = useState({ video: 1, image: 1 });
  const [autoUpscale, setAutoUpscale] = useState(() => {
    if (typeof window !== 'undefined') return localStorage.getItem('veo3_auto_upscale') || 'none';
    return 'none';
  });
  const [outputPath, setOutputPath] = useState(() => {
    if (typeof window !== 'undefined') return localStorage.getItem('veo3_output_path') || '';
    return '';
  });

  const isVideo = mediaTab === "video";
  const currentModels = isVideo ? VIDEO_MODELS : IMAGE_MODELS;
  const currentAspects = isVideo ? VIDEO_ASPECTS : IMAGE_ASPECTS;
  const currentModelKey = isVideo ? videoModel : imageModel;
  const currentModel = currentModels.find((m) => m.key === currentModelKey) || currentModels[0];
  const creditPerItem = isVideo ? creditCosts.video : creditCosts.image;
  const totalCredits = creditPerItem * numberOfOutputs;

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

  // Fetch credit costs from admin settings
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/credit-costs");
        if (res.ok) {
          const data = await res.json();
          setCreditCosts({ video: data.video_credits || 1, image: data.image_credits || 1 });
        }
      } catch { }
    })();
  }, []);

  // Always poll queue status
  useEffect(() => {
    if (!user) return;
    const interval = setInterval(fetchQueue, 5000);
    return () => clearInterval(interval);
  }, [user, fetchQueue]);

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

      {/* ═══ Video Sub-tabs: Khung hình / Thành phần ═══ */}
      {isVideo && (
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
            Chế độ:
          </label>
          <div className="flex rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
            <button
              onClick={() => setVideoSubTab("keyframes")}
              className="flex-1 flex items-center justify-center gap-1 py-2 text-xs font-medium transition-all"
              style={{
                background: videoSubTab === "keyframes" ? "var(--neon-blue)" : "transparent",
                color: videoSubTab === "keyframes" ? "white" : "var(--text-muted)",
              }}
            >
              <span className="material-symbols-rounded text-sm">view_carousel</span>
              Khung hình
            </button>
            <button
              onClick={() => setVideoSubTab("components")}
              className="flex-1 flex items-center justify-center gap-1 py-2 text-xs font-medium transition-all"
              style={{
                background: videoSubTab === "components" ? "var(--neon-blue)" : "transparent",
                color: videoSubTab === "components" ? "white" : "var(--text-muted)",
              }}
            >
              <span className="material-symbols-rounded text-sm">dashboard_customize</span>
              Thành phần
            </button>
          </div>
        </div>
      )}

      {/* ═══ Tỷ lệ (Aspect Ratio) ═══ */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
          Tỷ lệ:
        </label>
        <div className="grid grid-cols-2 gap-1.5">
          {currentAspects.map((ar) => (
            <button
              key={ar.value}
              onClick={() => setAspectRatio(ar.value)}
              className="flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-medium transition-all"
              style={{
                background: aspectRatio === ar.value ? "var(--neon-blue)" : "var(--bg-tertiary)",
                color: aspectRatio === ar.value ? "white" : "var(--text-secondary)",
                border: `1px solid ${aspectRatio === ar.value ? "var(--neon-blue)" : "var(--border-subtle)"}`,
              }}
            >
              <span className="material-symbols-rounded text-sm">{ar.icon}</span>
              {ar.label}
            </button>
          ))}
        </div>
      </div>

      {/* ═══ Số ô kết quả (x1-x4) ═══ */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
          Số lượng:
        </label>
        <div className="grid grid-cols-4 gap-1.5">
          {[1, 2, 3, 4].map((n) => (
            <button
              key={n}
              onClick={() => setNumberOfOutputs(n)}
              className="py-2 rounded-lg text-sm font-medium transition-all"
              style={{
                background: numberOfOutputs === n ? "var(--neon-blue)" : "var(--bg-tertiary)",
                color: numberOfOutputs === n ? "white" : "var(--text-secondary)",
                border: `1px solid ${numberOfOutputs === n ? "var(--neon-blue)" : "var(--border-subtle)"}`,
              }}
            >
              x{n}
            </button>
          ))}
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

      {/* ═══ Duration (4s / 6s / 8s) — Video only ═══ */}
      {isVideo && (
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
            Thời lượng:
          </label>
          <div className="grid grid-cols-3 gap-1.5">
            {(["4", "6", "8"] as const).map((d) => (
              <button
                key={d}
                onClick={() => setVideoDuration(d)}
                className="py-2 rounded-lg text-sm font-medium transition-all"
                style={{
                  background: videoDuration === d ? "var(--neon-blue)" : "var(--bg-tertiary)",
                  color: videoDuration === d ? "white" : "var(--text-secondary)",
                  border: `1px solid ${videoDuration === d ? "var(--neon-blue)" : "var(--border-subtle)"}`,
                }}
              >
                {d}s
              </button>
            ))}
          </div>
        </div>
      )}

      {/* ═══ Voice (Thành phần tab only) ═══ */}
      {isVideo && videoSubTab === "components" && (
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: "var(--text-muted)" }}>
            🎙️ Giọng nói:
          </label>
          <button
            onClick={() => setShowVoicePanel(!showVoicePanel)}
            className="w-full flex items-center justify-between py-2 px-3 rounded-lg text-xs font-medium transition-all"
            style={{
              background: selectedVoice ? "rgba(139,92,246,0.1)" : "var(--bg-tertiary)",
              color: selectedVoice ? "#a78bfa" : "var(--text-secondary)",
              border: `1px solid ${selectedVoice ? "#a78bfa" : "var(--border-subtle)"}`,
            }}
          >
            <span className="flex items-center gap-2">
              <span className="material-symbols-rounded text-sm">record_voice_over</span>
              {selectedVoice ? VOICES.find(v => v.id === selectedVoice)?.name || selectedVoice : "Chọn giọng nói"}
            </span>
            <span className="material-symbols-rounded text-sm">{showVoicePanel ? "expand_less" : "expand_more"}</span>
          </button>

          {showVoicePanel && (
            <div className="mt-2 rounded-lg overflow-hidden max-h-[250px] overflow-y-auto" style={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-subtle)",
            }}>
              {/* Clear voice */}
              {selectedVoice && (
                <button
                  onClick={() => { setSelectedVoice(null); setShowVoicePanel(false); }}
                  className="w-full text-left px-3 py-2 text-xs transition-colors flex items-center gap-2"
                  style={{ color: "var(--error)", borderBottom: "1px solid var(--border-subtle)" }}
                  onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg-hover)"}
                  onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <span className="material-symbols-rounded text-sm">close</span>
                  Bỏ giọng nói
                </button>
              )}
              {VOICES.map((v) => (
                <button
                  key={v.id}
                  onClick={() => { setSelectedVoice(v.id); setShowVoicePanel(false); }}
                  className="w-full text-left px-3 py-2.5 text-xs transition-colors flex items-center gap-2.5"
                  style={{
                    color: selectedVoice === v.id ? "white" : "var(--text-secondary)",
                    background: selectedVoice === v.id ? "rgba(139,92,246,0.2)" : "transparent",
                  }}
                  onMouseEnter={(e) => { if (selectedVoice !== v.id) e.currentTarget.style.background = "var(--bg-hover)"; }}
                  onMouseLeave={(e) => { if (selectedVoice !== v.id) e.currentTarget.style.background = "transparent"; }}
                >
                  <div className="w-7 h-7 rounded-full flex items-center justify-center shrink-0" style={{ background: v.color + "30" }}>
                    <span className="material-symbols-rounded" style={{ fontSize: "14px", color: v.color }}>graphic_eq</span>
                  </div>
                  <div>
                    <div className="font-semibold" style={{ color: "var(--text-primary)" }}>{v.name}</div>
                    <div style={{ color: "var(--text-muted)", fontSize: "10px" }}>{v.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ═══ Slot Counter ═══ */}
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

      {/* ═══ Account info ═══ */}
      {user && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>Tài khoản:</span>
            <span className="text-xs font-bold" style={{ color: "var(--neon-blue)" }}>{user.username}</span>
            <span className="text-xs" style={{ color: "var(--success)" }}>🟢</span>
          </div>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>
            Credits: <span className="font-bold" style={{ color: "#a855f7" }}>{(user.credits ?? 0).toLocaleString()}</span>
          </div>
          <div className="text-xs" style={{ color: "var(--text-muted)" }}>
            Số dư: <span className="font-bold" style={{ color: "var(--neon-blue)" }}>{(user.balance ?? 0).toLocaleString()}đ</span>
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
            <div className="fixed inset-0 z-40" onClick={() => setShowAdvanced(false)} />
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

              <button
                onClick={() => setShowAdvanced(false)}
                className="w-full py-2 rounded-lg text-xs font-bold transition-all"
                style={{ background: "var(--neon-blue)", color: "white", border: "none" }}
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
