/**
 * PromptBox — Prompt input with Bulk Import support
 * Features: single prompt, bulk import (file .txt / paste), style chips
 */
"use client";
import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
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
  const [showCreditModal, setShowCreditModal] = useState(false);
  const [creditCosts, setCreditCosts] = useState({ video: 1, image: 1 });
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const imageUploadRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

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

  const user = useStore((s) => s.user);
  const aspectRatio = useStore((s) => s.aspectRatio);
  const videoModel = useStore((s) => s.videoModel);
  const imageModel = useStore((s) => s.imageModel);
  const numberOfOutputs = useStore((s) => s.numberOfOutputs);
  const mediaTab = useStore((s) => s.mediaTab);
  const addActiveJob = useStore((s) => s.addActiveJob);
  const showToast = useStore((s) => s.showToast);
  const setUser = useStore((s) => s.setUser);
  const videoDuration = useStore((s) => s.videoDuration);
  const videoSubTab = useStore((s) => s.videoSubTab);
  const startImageId = useStore((s) => s.startImageId);
  const startImageUrl = useStore((s) => s.startImageUrl);
  const setStartImageId = useStore((s) => s.setStartImageId);
  const setStartImageUrl = useStore((s) => s.setStartImageUrl);
  const endImageId = useStore((s) => s.endImageId);
  const endImageUrl = useStore((s) => s.endImageUrl);
  const setEndImageId = useStore((s) => s.setEndImageId);
  const setEndImageUrl = useStore((s) => s.setEndImageUrl);
  const selectedVoice = useStore((s) => s.selectedVoice);
  const uploadedImages = useStore((s) => s.uploadedImages);
  const addUploadedImage = useStore((s) => s.addUploadedImage);
  const removeUploadedImage = useStore((s) => s.removeUploadedImage);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [activeFrame, setActiveFrame] = useState<"start" | "end">("start");
  const [showLibrary, setShowLibrary] = useState(false);

  const isVideo = mediaTab === "video";
  const currentModel = isVideo
    ? (VIDEO_MODELS.find((m) => m.key === videoModel) || VIDEO_MODELS[0])
    : (IMAGE_MODELS.find((m) => m.key === imageModel) || IMAGE_MODELS[0]);
  const creditPerItem = isVideo ? creditCosts.video : creditCosts.image;
  const totalCost = currentModel.price * numberOfOutputs;

  const parseBulkPrompts = (text: string) =>
    text.split("\n").map(l => l.trim()).filter(l => l.length > 0);

  const handleGenerate = async () => {
    if (!prompt.trim()) return showToast("Vui lòng nhập mô tả", "error");
    if (!user) return;

    // Pre-check credits
    const neededCredits = creditPerItem * numberOfOutputs;
    if ((user.credits ?? 0) < neededCredits) {
      setShowCreditModal(true);
      return;
    }

    const finalPrompt = selectedStyle ? `[${selectedStyle} style] ${prompt.trim()}` : prompt.trim();
    setGenerating(true);

    try {
      const modelKey = isVideo ? videoModel : (useStore.getState() as any).imageModel || "nano_banana_pro";
      const res = await api.generate({
        prompt: finalPrompt,
        aspect_ratio: aspectRatio,
        number_of_outputs: numberOfOutputs,
        video_model: modelKey,
        ...(isVideo && startImageId ? { start_image_id: startImageId } : {}),
        ...(isVideo ? { duration: videoDuration } : {}),
        ...(isVideo && selectedVoice ? { voice: selectedVoice } : {}),
      });

      if (res.success) {
        const allIds: number[] = res.job_ids || [res.job_id];
        showToast(`🎬 Đang tạo ${allIds.length} ${isVideo ? "video" : "ảnh"}...`, "success");
        setUser({ ...user, credits: res.remaining_balance });
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
      const msg = e.message || "Lỗi tạo";
      if (msg.includes("balance") || msg.includes("credit") || msg.includes("Insufficient") || msg.includes("không đủ")) {
        setShowCreditModal(true);
      } else {
        showToast(msg, "error");
      }
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
        setUser({ ...user, credits: res.remaining_balance });
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
      const msg = e.message || "Lỗi bulk generate";
      if (msg.includes("balance") || msg.includes("credit") || msg.includes("Insufficient") || msg.includes("không đủ")) {
        setShowCreditModal(true);
      } else {
        showToast(msg, "error");
      }
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

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>, target: "start" | "end" = "start") => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      showToast("Chỉ hỗ trợ file ảnh", "error");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      showToast("Ảnh quá lớn (tối đa 10MB)", "error");
      return;
    }

    setUploadingImage(true);
    try {
      const formData = new FormData();
      formData.append("image", file);
      const token = localStorage.getItem("veo3_token");
      const res = await fetch("/api/upload-image", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      const data = await res.json();
      if (data.success && data.media_id) {
        // Server saved image and returned public_url
        const publicUrl = data.public_url || data.url || "";
        // Create data URL for local preview in library
        const reader = new FileReader();
        reader.onload = () => {
          const dataUrl = reader.result as string;
          // Save to library — mediaId stores the public_url for generation
          addUploadedImage({
            id: `img-${Date.now()}`,
            mediaId: publicUrl, // public URL for NanoAI API
            url: dataUrl,       // data URL for local preview
            name: file.name,
            uploadedAt: Date.now(),
          });
          // Set as active reference — startImageId = public URL
          if (target === "start") {
            setStartImageId(publicUrl);
            setStartImageUrl(dataUrl);
          } else {
            setEndImageId(publicUrl);
            setEndImageUrl(dataUrl);
          }
        };
        reader.readAsDataURL(file);
        showToast(`✅ Đã tải ảnh lên!`, "success");
        setShowLibrary(false);
      } else {
        showToast(data.detail || "Lỗi upload ảnh", "error");
      }
    } catch (err: any) {
      showToast(err.message || "Lỗi upload ảnh", "error");
    } finally {
      setUploadingImage(false);
      if (imageUploadRef.current) imageUploadRef.current.value = "";
    }
  };

  // Select image from library
  const selectFromLibrary = (img: { mediaId: string; url: string }) => {
    if (activeFrame === "start") {
      setStartImageId(img.mediaId);
      setStartImageUrl(img.url);
    } else {
      setEndImageId(img.mediaId);
      setEndImageUrl(img.url);
    }
    setShowLibrary(false);
    showToast("✅ Đã chọn ảnh!", "success");
  };

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
            borderRadius: "24px",
          }}>

          {/* ═══ Keyframe frames INSIDE prompt box ═══ */}
          {isVideo && videoSubTab === "keyframes" && (
            <div className="flex items-center gap-2.5 mb-3 pb-3" style={{ borderBottom: "1px solid var(--prompt-border)" }}>
              {/* Start frame */}
              <div
                className="relative rounded-xl overflow-hidden cursor-pointer group transition-all shrink-0"
                style={{
                  width: 64, height: 64,
                  border: activeFrame === "start" ? "2px solid var(--neon-blue)" : "2px solid var(--border-subtle)",
                  background: "var(--bg-tertiary)",
                  borderRadius: "14px",
                }}
                onClick={() => { setActiveFrame("start"); imageUploadRef.current?.click(); }}
              >
                {startImageUrl ? (
                  <img src={startImageUrl} alt="Start" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex flex-col items-center justify-center gap-0.5">
                    <span className="material-symbols-rounded" style={{ color: "var(--text-muted)", fontSize: "20px" }}>add_photo_alternate</span>
                    <span className="text-[8px] font-semibold" style={{ color: "var(--text-muted)" }}>Bắt đầu</span>
                  </div>
                )}
                {startImageUrl && (
                  <button
                    onClick={(e) => { e.stopPropagation(); setStartImageId(null); setStartImageUrl(null); }}
                    className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                    style={{ background: "rgba(0,0,0,0.6)" }}
                  >
                    <span className="material-symbols-rounded text-white" style={{ fontSize: "10px" }}>close</span>
                  </button>
                )}
              </div>

              <span className="material-symbols-rounded shrink-0" style={{ color: "var(--text-muted)", fontSize: "16px" }}>swap_horiz</span>

              {/* End frame */}
              <div
                className="relative rounded-xl overflow-hidden cursor-pointer group transition-all shrink-0"
                style={{
                  width: 64, height: 64,
                  border: activeFrame === "end" ? "2px solid var(--neon-purple)" : "2px solid var(--border-subtle)",
                  background: "var(--bg-tertiary)",
                  borderRadius: "14px",
                }}
                onClick={() => { setActiveFrame("end"); imageUploadRef.current?.click(); }}
              >
                {endImageUrl ? (
                  <img src={endImageUrl} alt="End" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex flex-col items-center justify-center gap-0.5">
                    <span className="material-symbols-rounded" style={{ color: "var(--text-muted)", fontSize: "20px" }}>add_photo_alternate</span>
                    <span className="text-[8px] font-semibold" style={{ color: "var(--text-muted)" }}>Kết thúc</span>
                  </div>
                )}
                {endImageUrl && (
                  <button
                    onClick={(e) => { e.stopPropagation(); setEndImageId(null); setEndImageUrl(null); }}
                    className="absolute top-0.5 right-0.5 w-4 h-4 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                    style={{ background: "rgba(0,0,0,0.6)" }}
                  >
                    <span className="material-symbols-rounded text-white" style={{ fontSize: "10px" }}>close</span>
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Image preview (if uploaded in Components or Image mode) */}
          {((!isVideo) || (isVideo && videoSubTab === "components")) && startImageUrl && (
            <div className="flex items-center gap-2 mb-2 pb-2" style={{ borderBottom: "1px solid var(--prompt-border)" }}>
              <div className="relative rounded-lg overflow-hidden" style={{ width: 48, height: 48 }}>
                <img src={startImageUrl} alt="Ref" className="w-full h-full object-cover" />
                <button
                  onClick={() => { setStartImageId(null); setStartImageUrl(null); }}
                  className="absolute top-0 right-0 w-4 h-4 rounded-full flex items-center justify-center"
                  style={{ background: "rgba(0,0,0,0.6)" }}
                >
                  <span className="material-symbols-rounded text-white" style={{ fontSize: "10px" }}>close</span>
                </button>
              </div>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>Ảnh tham chiếu đã tải lên</span>
            </div>
          )}

          {/* Header row with textarea and button */}
          <div className="flex items-end gap-3">
            {/* Upload image (+) button — LEFT side like Flow Labs */}
            <input
              ref={imageUploadRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => handleImageUpload(e, activeFrame)}
            />
            {((!isVideo) || (isVideo && videoSubTab === "components")) && (
              <button
                onClick={() => setShowLibrary(true)}
                className="shrink-0 flex items-center justify-center rounded-full transition-all hover:scale-105"
                title="Thư viện ảnh"
                style={{
                  width: 40, height: 40,
                  border: "2px solid var(--border-subtle)",
                  background: "var(--bg-tertiary)",
                  color: uploadingImage ? "var(--text-muted)" : "var(--text-secondary)",
                }}
                disabled={uploadingImage}
              >
                {uploadingImage ? (
                  <span className="spinner !w-5 !h-5 !border-current/20 !border-t-current"></span>
                ) : (
                  <span className="material-symbols-rounded" style={{ fontSize: "22px" }}>add</span>
                )}
              </button>
            )}
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
                  ? "Bạn muốn tạo gì?"
                  : "Mô tả hình ảnh bạn muốn tạo..."}
                rows={1}
                className="w-full bg-transparent resize-none outline-none text-[14px] leading-relaxed placeholder:text-[var(--prompt-placeholder)]"
                style={{ color: "var(--prompt-text)", minHeight: "36px", maxHeight: "120px" }}
                disabled={generating}
              />
            </div>
            {/* Quick actions — RIGHT side */}
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
                    Generate
                  </>
                )}
              </button>
            </div>
          </div>
          {/* Info bar */}
          <div className="flex items-center gap-3 mt-2 pt-2" style={{ borderTop: "1px solid var(--prompt-border)" }}>
            <span className="text-xs" style={{ color: "var(--prompt-placeholder)" }}>
              {isVideo ? `Video · ${videoDuration}s` : currentModel.label} · {aspectRatio} · x{numberOfOutputs}
              {startImageId ? " · 📷 Ảnh" : ""}
              {selectedVoice ? " · 🎙️" : ""}
            </span>
            <span className="badge badge-neon !text-[10px]">{(creditPerItem * numberOfOutputs)} credits</span>
          </div>
        </div>
      </div>

      {/* ═══ IMAGE LIBRARY MODAL ═══ */}
      {showLibrary && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)" }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowLibrary(false); }}
        >
          <div className="glass-card p-0 w-full max-w-[700px] max-h-[80vh] mx-4 flex flex-col overflow-hidden"
            style={{ borderRadius: "20px" }}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
              <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>Thư viện ảnh</h3>
              <button
                onClick={() => setShowLibrary(false)}
                className="btn-ghost !p-1 !rounded-lg"
              >
                <span className="material-symbols-rounded text-lg" style={{ color: "var(--text-muted)" }}>close</span>
              </button>
            </div>

            {/* Image Grid */}
            <div className="flex-1 overflow-y-auto p-4" style={{ minHeight: "200px" }}>
              {uploadedImages.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 gap-3">
                  <span className="material-symbols-rounded" style={{ fontSize: "48px", color: "var(--text-muted)" }}>photo_library</span>
                  <p className="text-sm" style={{ color: "var(--text-muted)" }}>Không tìm thấy kết quả nào</p>
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>Tải ảnh lên để sử dụng làm tham chiếu</p>
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-3">
                  {uploadedImages.map((img) => (
                    <div
                      key={img.id}
                      className="relative rounded-xl overflow-hidden cursor-pointer group transition-all hover:ring-2 hover:ring-[var(--neon-blue)]"
                      style={{ aspectRatio: "1", background: "var(--bg-tertiary)" }}
                      onClick={() => selectFromLibrary(img)}
                    >
                      <img src={img.url} alt={img.name} className="w-full h-full object-cover" />
                      {/* Selected indicator */}
                      {startImageId === img.mediaId && (
                        <div className="absolute top-1.5 left-1.5 w-5 h-5 rounded-full flex items-center justify-center"
                          style={{ background: "var(--neon-blue)" }}
                        >
                          <span className="material-symbols-rounded text-white" style={{ fontSize: "14px" }}>check</span>
                        </div>
                      )}
                      {/* Delete button */}
                      <button
                        onClick={(e) => { e.stopPropagation(); removeUploadedImage(img.id); }}
                        className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                        style={{ background: "rgba(0,0,0,0.7)" }}
                      >
                        <span className="material-symbols-rounded text-white" style={{ fontSize: "14px" }}>delete</span>
                      </button>
                      {/* Name */}
                      <div className="absolute bottom-0 left-0 right-0 px-2 py-1 opacity-0 group-hover:opacity-100 transition-opacity"
                        style={{ background: "linear-gradient(transparent, rgba(0,0,0,0.7))" }}
                      >
                        <p className="text-[10px] text-white truncate">{img.name}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Footer — Upload button */}
            <div className="px-5 py-4 flex items-center gap-3" style={{ borderTop: "1px solid var(--border-subtle)" }}>
              <input
                ref={imageUploadRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={(e) => handleImageUpload(e, activeFrame)}
              />
              <button
                onClick={() => imageUploadRef.current?.click()}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl transition-all hover:scale-[1.02]"
                style={{
                  border: "1.5px solid var(--border-subtle)",
                  background: "var(--bg-tertiary)",
                  color: "var(--text-primary)",
                }}
                disabled={uploadingImage}
              >
                {uploadingImage ? (
                  <span className="spinner !w-4 !h-4 !border-current/20 !border-t-current"></span>
                ) : (
                  <span className="material-symbols-rounded" style={{ fontSize: "18px" }}>upload</span>
                )}
                <span className="text-sm font-medium">Tải hình ảnh lên</span>
              </button>
            </div>
          </div>
        </div>
      )}

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
              <span className="badge badge-neon">{(creditPerItem * numberOfOutputs * bulkPrompts.length)} credits</span>
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

      {/* ═══ INSUFFICIENT CREDIT MODAL ═══ */}
      {showCreditModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)" }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowCreditModal(false); }}>
          <div className="glass-card p-8 w-full max-w-md mx-4 text-center"
            style={{ border: "1px solid var(--border-accent)", boxShadow: "0 0 40px rgba(239,68,68,0.15)" }}>
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full mb-4"
              style={{ background: "rgba(239,68,68,0.1)", border: "3px solid #ef4444" }}>
              <span className="material-symbols-rounded text-3xl" style={{ color: "#ef4444" }}>credit_card_off</span>
            </div>
            <h2 className="text-xl font-bold mb-2" style={{ color: "var(--text-primary)" }}>Hết Credit!</h2>
            <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
              Bạn không đủ credit để tạo. Hãy mua gói đăng ký hoặc nạp thêm tiền.
            </p>
            <div className="flex gap-3 justify-center">
              <button onClick={() => { setShowCreditModal(false); router.push("/plans"); }}
                className="px-5 py-2.5 rounded-xl text-sm font-semibold text-white"
                style={{ background: "linear-gradient(135deg, var(--neon-blue), var(--neon-purple))" }}>
                <span className="flex items-center gap-1.5">
                  <span className="material-symbols-rounded text-base">workspace_premium</span>
                  Mua gói
                </span>
              </button>
              <button onClick={() => { setShowCreditModal(false); router.push("/plans?tab=deposit"); }}
                className="px-5 py-2.5 rounded-xl text-sm font-semibold text-white"
                style={{ background: "linear-gradient(135deg, #10b981, #059669)" }}>
                <span className="flex items-center gap-1.5">
                  <span className="material-symbols-rounded text-base">account_balance_wallet</span>
                  Nạp tiền
                </span>
              </button>
            </div>
            <button onClick={() => setShowCreditModal(false)} className="mt-4 text-xs underline"
              style={{ color: "var(--text-muted)" }}>Đóng</button>
          </div>
        </div>
      )}
    </>
  );
}

