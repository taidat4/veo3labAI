/**
 * PromptBox — Prompt input with Bulk Import support
 * Features: single prompt, bulk import (file .txt / paste), style chips
 */
"use client";
import { useState, useRef } from "react";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";

// Re-export for use in SettingsPanel and other components
export const VIDEO_MODELS = [
  { key: "veo31_fast_lp", label: "Veo 3.1 - Quality", credits: 1, price: 3000, icon: "🎬", desc: "Chất lượng cao" },
];

export const IMAGE_MODELS = [
  { key: "nano_banana_pro", label: "Nano Banana Pro", credits: 1, price: 1500, icon: "👍", desc: "Miễn phí" },
  { key: "nano_banana_2", label: "Nano Banana 2", credits: 1, price: 1000, icon: "👍", desc: "Miễn phí" },
  { key: "imagen_4", label: "Imagen 4", credits: 1, price: 2000, icon: "", desc: "Cao cấp" },
];

export const VIDEO_ASPECTS = [
  { value: "9:16", label: "Dọc 9:16", icon: "crop_portrait" },
  { value: "16:9", label: "Ngang 16:9", icon: "crop_landscape" },
];

export const IMAGE_ASPECTS = [
  { value: "16:9", label: "16:9", icon: "crop_landscape" },
  { value: "4:3", label: "4:3", icon: "crop_din" },
  { value: "1:1", label: "1:1", icon: "crop_square" },
  { value: "3:4", label: "3:4", icon: "crop_3_2" },
  { value: "9:16", label: "9:16", icon: "crop_portrait" },
];

const STYLES = [
  "Cinematic", "Realistic", "Anime", "Vibrant", "Dreamy",
  "Film Noir", "Retro VHS", "Abstract", "Nature", "Sci-Fi",
];

export function PromptBox({ onRefreshHistory }: { onRefreshHistory: () => void }) {
  const [prompt, setPrompt] = useState("");
  const [generating, setGenerating] = useState(false);
  const [selectedStyle, setSelectedStyle] = useState("");
  const [showBulkModal, setShowBulkModal] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [bulkSubmitting, setBulkSubmitting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const user = useStore((s) => s.user);
  const aspectRatio = useStore((s) => s.aspectRatio);
  const videoModel = useStore((s) => s.videoModel);
  const imageModel = useStore((s) => s.imageModel);
  const numberOfOutputs = useStore((s) => s.numberOfOutputs);
  const mediaTab = useStore((s) => s.mediaTab);
  const addActiveJob = useStore((s) => s.addActiveJob);
  const showToast = useStore((s) => s.showToast);
  const setUser = useStore((s) => s.setUser);

  const isVideo = mediaTab === "video";
  const currentModel = isVideo
    ? (VIDEO_MODELS.find((m) => m.key === videoModel) || VIDEO_MODELS[0])
    : (IMAGE_MODELS.find((m) => m.key === imageModel) || IMAGE_MODELS[0]);
  const totalCost = currentModel.price * numberOfOutputs;

  const parseBulkPrompts = (text: string) =>
    text.split("\n").map(l => l.trim()).filter(l => l.length > 0);

  const handleGenerate = async () => {
    if (!prompt.trim()) return showToast("Vui lòng nhập mô tả", "error");
    if (!user) return;

    const finalPrompt = selectedStyle ? `[${selectedStyle} style] ${prompt.trim()}` : prompt.trim();
    setGenerating(true);

    try {
      const modelKey = isVideo ? videoModel : (useStore.getState() as any).imageModel || "nano_banana_pro";
      const res = await api.generate({
        prompt: finalPrompt,
        aspect_ratio: aspectRatio,
        number_of_outputs: numberOfOutputs,
        video_model: modelKey,
      });

      if (res.success) {
        const allIds: number[] = res.job_ids || [res.job_id];
        showToast(`🎬 Đang tạo ${allIds.length} ${isVideo ? "video" : "ảnh"}...`, "success");
        setUser({ ...user, balance: res.remaining_balance });
        allIds.forEach((jid: number) => {
          addActiveJob({
            id: jid,
            prompt: finalPrompt,
            status: "queued",
            progress: 0,
            mediaType: isVideo ? "video" : "image",
            startedAt: Date.now(),
          });
        });
        setPrompt("");
        onRefreshHistory();
      }
    } catch (e: any) {
      showToast(e.message || "Lỗi tạo", "error");
    } finally {
      setGenerating(false);
    }
  };

  const handleBulkGenerate = async () => {
    const prompts = parseBulkPrompts(bulkText);
    if (prompts.length === 0) return showToast("Không có prompt nào!", "error");
    if (!user) return;

    setBulkSubmitting(true);
    try {
      const modelKey = isVideo ? videoModel : (useStore.getState() as any).imageModel || "nano_banana_pro";
      const finalPrompts = selectedStyle
        ? prompts.map(p => `[${selectedStyle} style] ${p}`)
        : prompts;

      const res = await api.generateBulk({
        prompts: finalPrompts,
        aspect_ratio: aspectRatio,
        number_of_outputs: numberOfOutputs,
        video_model: modelKey,
      });

      if (res.success) {
        showToast(`🎬 Đang tạo ${res.job_ids?.length || prompts.length} ${isVideo ? "video" : "ảnh"}!`, "success");
        setUser({ ...user, balance: res.remaining_balance });
        (res.job_ids || []).forEach((id: number, idx: number) => {
          addActiveJob({
            id,
            prompt: finalPrompts[Math.min(idx, finalPrompts.length - 1)] || "",
            status: "queued",
            progress: 0,
            mediaType: isVideo ? "video" : "image",
            startedAt: Date.now(),
          });
        });
        setShowBulkModal(false);
        setBulkText("");
        onRefreshHistory();
      }
    } catch (e: any) {
      showToast(e.message || "Lỗi bulk generate", "error");
    } finally {
      setBulkSubmitting(false);
    }
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      setBulkText(text);
      setShowBulkModal(true);
    };
    reader.readAsText(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleGenerate();
    }
  };

  const autoResize = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setPrompt(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 240) + "px";
  };

  const magicPrompts = [
    "A majestic dragon soaring through aurora-lit skies over misty mountains, cinematic 4K",
    "Futuristic neon city at night with flying cars and holograms, cyberpunk style",
    "A serene Japanese garden with cherry blossoms falling, gentle wind, close-up macro",
    "Underwater coral reef with colorful tropical fish, sunlight rays, nature documentary",
  ];

  const bulkPrompts = parseBulkPrompts(bulkText);
  const bulkTotalCost = currentModel.price * numberOfOutputs * bulkPrompts.length;

  return (
    <>
      <div className="flex flex-col gap-3 w-full fade-in" style={{ padding: "0 300px" }}>
        {/* ═══ Main prompt area ═══ */}
        <div className="px-4 py-3"
          style={{
            background: "var(--prompt-bg)",
            border: generating ? "1.5px solid var(--neon-blue)" : "1.5px solid var(--prompt-border)",
            boxShadow: generating ? "0 0 12px rgba(79,70,229,0.15)" : "0 2px 16px rgba(0,0,0,0.08)",
            backdropFilter: "blur(16px)",
            borderRadius: "30px",
          }}>
          {/* Header row with textarea and button */}
          <div className="flex items-end gap-3">
            <div className="flex-1 min-w-0">
              <textarea
                ref={textareaRef}
                value={prompt}
                onChange={(e) => {
                  setPrompt(e.target.value);
                  const el = e.target;
                  el.style.height = "auto";
                  el.style.height = Math.min(el.scrollHeight, 120) + "px";
                }}
                onKeyDown={handleKeyDown}
                placeholder={isVideo
                  ? "Mô tả video bạn muốn tạo... (Enter để tạo, Shift+Enter xuống dòng)"
                  : "Mô tả hình ảnh bạn muốn tạo... (Enter để tạo, Shift+Enter xuống dòng)"}
                rows={1}
                className="w-full bg-transparent resize-none outline-none text-[14px] leading-relaxed placeholder:text-[var(--prompt-placeholder)]"
                style={{ color: "var(--prompt-text)", minHeight: "36px", maxHeight: "120px" }}
                disabled={generating}
              />
            </div>
            {/* Quick actions */}
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                onClick={() => setPrompt(magicPrompts[Math.floor(Math.random() * magicPrompts.length)])}
                className="btn-ghost !p-1.5 !rounded-lg"
                title="Magic Prompt"
                style={{ color: "var(--neon-purple)" }}
              >
                <span className="material-symbols-rounded text-lg">magic_button</span>
              </button>
              <input ref={fileInputRef} type="file" accept=".txt" className="hidden" onChange={handleFileUpload} />
              <button
                onClick={() => setShowBulkModal(true)}
                className="btn-ghost !p-1.5 !rounded-lg"
                title="Bulk Import"
                style={{ color: "var(--neon-blue)" }}
              >
                <span className="material-symbols-rounded text-lg">upload_file</span>
              </button>
              <button
                onClick={handleGenerate}
                disabled={generating || !prompt.trim()}
                className="btn-generate !py-2.5 !px-5 flex items-center gap-2 !text-sm"
              >
                {generating ? (
                  <>
                    <span className="spinner !w-4 !h-4 !border-white/20 !border-t-white"></span>
                    Đang tạo...
                  </>
                ) : (
                  <>
                    <span className="material-symbols-rounded text-lg">play_arrow</span>
                    {isVideo ? "Generate" : "Generate"}
                  </>
                )}
              </button>
            </div>
          </div>
          {/* Info bar */}
          <div className="flex items-center gap-3 mt-2 pt-2" style={{ borderTop: "1px solid var(--prompt-border)" }}>
            <span className="text-xs" style={{ color: "var(--prompt-placeholder)" }}>
              {currentModel.label} · {aspectRatio} · x{numberOfOutputs}
            </span>
            <span className="badge badge-neon !text-[10px]">{(currentModel.credits * numberOfOutputs)} credits</span>
          </div>
        </div>
      </div>

      {/* ═══ BULK IMPORT MODAL ═══ */}
      {showBulkModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)" }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowBulkModal(false); }}
        >
          <div className="glass-card p-6 w-full max-w-[700px] max-h-[85vh] overflow-y-auto mx-4"
            style={{ border: "1px solid var(--neon-blue)", boxShadow: "0 0 40px rgba(79,172,254,0.15)" }}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className="material-symbols-rounded text-xl" style={{ color: "var(--neon-blue)" }}>playlist_add</span>
                <h2 className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
                  Bulk Import Prompts
                </h2>
              </div>
              <button onClick={() => setShowBulkModal(false)} className="btn-ghost !p-1">
                <span className="material-symbols-rounded">close</span>
              </button>
            </div>

            <div className="flex gap-2 mb-3">
              <button
                onClick={() => fileInputRef.current?.click()}
                className="btn-ghost !text-xs flex items-center gap-1"
                style={{ color: "var(--neon-purple)", border: "1px solid var(--border-subtle)", padding: "6px 12px", borderRadius: "8px" }}
              >
                <span className="material-symbols-rounded text-sm">attach_file</span>
                Chọn file .txt
              </button>
              <span className="text-xs self-center" style={{ color: "var(--text-muted)" }}>
                hoặc paste trực tiếp (mỗi dòng = 1 prompt)
              </span>
            </div>

            <textarea
              value={bulkText}
              onChange={(e) => setBulkText(e.target.value)}
              placeholder={"Dán prompt vào đây — mỗi dòng là 1 prompt:\n\nA cute cat playing with yarn\nA beautiful sunset over the ocean\nA futuristic city at night with neon lights"}
              rows={10}
              className="w-full rounded-lg p-3 text-sm resize-none outline-none"
              style={{
                background: "var(--bg-secondary)",
                color: "var(--text-primary)",
                border: "1px solid var(--border-subtle)",
                fontFamily: "monospace",
              }}
            />

            <div className="flex items-center justify-between mt-3 mb-2">
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                {bulkPrompts.length > 0 ? (
                  <>
                    <strong style={{ color: "var(--neon-blue)" }}>{bulkPrompts.length}</strong> prompts
                    {" · "}{currentModel.label} · x{numberOfOutputs}
                    {" · "}<strong>{bulkPrompts.length * numberOfOutputs}</strong> {isVideo ? "videos" : "images"}
                  </>
                ) : "Chưa có prompt nào"}
              </span>
              <span className="badge badge-neon">{(currentModel.credits * numberOfOutputs * bulkPrompts.length)} credits</span>
            </div>

            {bulkPrompts.length > 0 && (
              <div className="rounded-lg p-2 max-h-[200px] overflow-y-auto mb-3"
                style={{ background: "var(--bg-primary)", border: "1px solid var(--border-subtle)" }}>
                {bulkPrompts.slice(0, 20).map((p, i) => (
                  <div key={i} className="flex items-start gap-2 py-1 px-2 text-xs"
                    style={{ color: "var(--text-secondary)" }}>
                    <span className="shrink-0 w-5 text-right font-mono" style={{ color: "var(--text-muted)" }}>
                      {i + 1}.
                    </span>
                    <span className="line-clamp-1">{p}</span>
                  </div>
                ))}
                {bulkPrompts.length > 20 && (
                  <div className="text-xs text-center py-1" style={{ color: "var(--text-muted)" }}>
                    ...và {bulkPrompts.length - 20} prompt khác
                  </div>
                )}
              </div>
            )}

            <div className="flex justify-end gap-2 mt-2">
              <button onClick={() => setShowBulkModal(false)} className="btn-ghost">Hủy</button>
              <button
                onClick={handleBulkGenerate}
                disabled={bulkSubmitting || bulkPrompts.length === 0}
                className="btn-generate flex items-center gap-2"
              >
                {bulkSubmitting ? (
                  <>
                    <span className="spinner !w-4 !h-4 !border-white/20 !border-t-white"></span>
                    Đang gửi...
                  </>
                ) : (
                  <>
                    <span className="material-symbols-rounded">rocket_launch</span>
                    Generate {bulkPrompts.length} {isVideo ? "video" : "ảnh"}
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
