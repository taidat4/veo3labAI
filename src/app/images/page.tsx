/**
 * My Images Page — Grid toàn bộ ảnh đã tạo
 * Features:
 *   - Multi-select checkbox để chọn nhiều ảnh
 *   - "Tải tất cả" (Download All selected) button
 *   - Filter (Tất cả / Thành công / Thất bại)
 *   - Grid mode selector (2/3/4/6 columns)
 *   - Resolution filter (All / Upscaled)
 *   - 60 per page max
 *   - Full-width layout
 */
"use client";
import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useStore, type HistoryJob } from "@/lib/store";
import { api, API_BASE } from "@/lib/api";
import { Navbar } from "@/components/Navbar";
import { Toast } from "@/components/Toast";
import { VideoPreviewModal } from "@/components/VideoPreviewModal";

const GRID_MODES = [
    { cols: 2, icon: "grid_on", label: "Lớn" },
    { cols: 3, icon: "grid_view", label: "Vừa" },
    { cols: 4, icon: "apps", label: "Nhỏ" },
    { cols: 6, icon: "view_comfy", label: "Mini" },
] as const;

const ITEMS_PER_PAGE = 60;

export default function ImagesPage() {
    const router = useRouter();
    const user = useStore((s) => s.user);
    const setUser = useStore((s) => s.setUser);
    const history = useStore((s) => s.history);
    const setHistory = useStore((s) => s.setHistory);
    const showToast = useStore((s) => s.showToast);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState<"all" | "completed" | "failed">("all");
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
    const [downloading, setDownloading] = useState(false);
    const [resFilter, setResFilter] = useState("all"); // "all" | "upscaled"
    const [gridCols, setGridCols] = useState(6);

    useEffect(() => {
        const stored = localStorage.getItem("veo3_user");
        const token = localStorage.getItem("veo3_token");
        if (stored && token) {
            setUser({ ...JSON.parse(stored), token });
        } else {
            router.push("/login");
        }
        const savedGrid = localStorage.getItem("veo3_grid_cols_images");
        if (savedGrid) setGridCols(parseInt(savedGrid));

        // ── Load cached history instantly from localStorage ──
        try {
            const cached = localStorage.getItem("veo3_history_cache");
            if (cached) {
                const jobs = JSON.parse(cached);
                if (Array.isArray(jobs) && jobs.length > 0) {
                    setHistory(jobs);
                    setLoading(false);
                }
            }
        } catch { }
    }, [router, setUser, setHistory]);

    const fetchAll = useCallback(async () => {
        try {
            const data = await api.getJobs(80);
            const jobs = data.jobs || [];
            setHistory(jobs);
            // Cache for instant next load
            try { localStorage.setItem("veo3_history_cache", JSON.stringify(jobs)); } catch { }
        } catch { } finally {
            setLoading(false);
        }
    }, [setHistory]);

    useEffect(() => { if (user) fetchAll(); }, [user, fetchAll]);

    // Filter only images
    const allImages = history.filter((j) => j.media_type === "image");

    const filtered = allImages.filter((j) => {
        if (filter === "all") return true;
        return j.status === filter;
    });

    const displayedJobs = filtered.slice(0, ITEMS_PER_PAGE);

    // Resolution filter
    const visibleJobs = resFilter === "upscaled"
        ? displayedJobs.filter((j) => j.status === "completed" && !!j.upscale_url)
        : displayedJobs;

    const completedFiltered = visibleJobs.filter((j) => j.status === "completed" && (j.video_url || j.r2_url));

    const totalCost = allImages.reduce((sum, j) => sum + (j.cost || 0), 0);

    // ── Selection helpers ──
    const toggleSelect = (id: number) => {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    const selectAll = () => {
        const allIds = completedFiltered.map(j => j.id);
        setSelectedIds(new Set(allIds));
    };

    const deselectAll = () => setSelectedIds(new Set());

    const handleBulkDownload = async () => {
        if (selectedIds.size === 0) return showToast("Chưa chọn ảnh nào", "error");
        setDownloading(true);
        showToast(`⬇️ Đang tải ${selectedIds.size} ảnh...`, "info");

        const idsArr = Array.from(selectedIds);
        for (let i = 0; i < idsArr.length; i++) {
            const job = allImages.find(j => j.id === idsArr[i]);
            const url = job?.video_url || job?.r2_url;
            if (!url) continue;
            const dlUrl = url.startsWith("/") ? `${API_BASE}${url}` : url;
            try {
                const resp = await fetch(dlUrl);
                const blob = await resp.blob();
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `image-${idsArr[i]}.png`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(a.href);
            } catch {
                window.open(dlUrl, "_blank");
            }
            if (i < idsArr.length - 1) {
                await new Promise(r => setTimeout(r, 500));
            }
        }

        setDownloading(false);
        showToast(`✅ Đã tải ${idsArr.length} ảnh`, "success");
    };

    const handleGridChange = (cols: number) => {
        setGridCols(cols);
        localStorage.setItem("veo3_grid_cols_images", String(cols));
    };

    const gridClass = {
        2: "grid-cols-1 sm:grid-cols-2",
        3: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3",
        4: "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
        6: "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6",
    }[gridCols] || "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6";

    if (!user) return null;

    return (
        <div className="min-h-screen" style={{ background: "var(--bg-primary)" }}>
            <Toast />
            <Navbar />
            <main className="pt-16 px-4 sm:px-6 w-full">
                {/* Header */}
                <div className="flex items-center justify-between py-8 flex-wrap gap-4">
                    <div>
                        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>My Images</h1>
                        <p className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
                            {visibleJobs.length} ảnh{resFilter === "upscaled" ? " đã upscale" : ""} · Tổng {visibleJobs.reduce((s, j) => s + (j.cost || 0), 0).toLocaleString()} credits
                            {visibleJobs.length !== allImages.length && (
                                <span> (tổng cộng {allImages.length})</span>
                            )}
                        </p>
                    </div>

                    <div className="flex items-center gap-3 flex-wrap">
                        {/* Filter */}
                        {(["all", "completed", "failed"] as const).map((f) => (
                            <button key={f}
                                onClick={() => { setFilter(f); setSelectedIds(new Set()); }}
                                className={`chip text-xs ${filter === f ? "chip-active" : ""}`}>
                                {f === "all" ? "Tất cả" : f === "completed" ? "✅ Thành công" : "❌ Thất bại"}
                            </button>
                        ))}

                        {/* Separator */}
                        <div style={{ width: 1, height: 24, background: "var(--border-subtle)" }} />

                        {/* Grid mode selector */}
                        <div className="flex items-center rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
                            {GRID_MODES.map((mode) => (
                                <button
                                    key={mode.cols}
                                    onClick={() => handleGridChange(mode.cols)}
                                    className="px-2.5 py-1.5 transition-all"
                                    title={mode.label}
                                    style={{
                                        background: gridCols === mode.cols ? "var(--neon-blue)" : "transparent",
                                        color: gridCols === mode.cols ? "white" : "var(--text-muted)",
                                    }}
                                >
                                    <span className="material-symbols-rounded text-base">{mode.icon}</span>
                                </button>
                            ))}
                        </div>

                        {/* Separator */}
                        <div style={{ width: 1, height: 24, background: "var(--border-subtle)" }} />

                        {/* Resolution filter */}
                        <select
                            value={resFilter}
                            onChange={(e) => setResFilter(e.target.value)}
                            className="text-xs rounded-lg px-2 py-1.5 outline-none"
                            style={{
                                background: "var(--bg-secondary)",
                                color: "var(--text-primary)",
                                border: "1px solid var(--border-subtle)",
                            }}
                        >
                            <option value="all">Tất cả</option>
                            <option value="upscaled">Đã Upscale</option>
                        </select>

                        {/* Multi-select controls */}
                        {completedFiltered.length > 0 && (
                            <>
                                <button
                                    onClick={selectedIds.size === completedFiltered.length ? deselectAll : selectAll}
                                    className="btn-ghost !text-xs flex items-center gap-1"
                                    style={{ color: "var(--neon-blue)" }}
                                >
                                    <span className="material-symbols-rounded text-sm">
                                        {selectedIds.size === completedFiltered.length ? "deselect" : "select_all"}
                                    </span>
                                    {selectedIds.size === completedFiltered.length ? "Bỏ chọn" : "Chọn tất cả"}
                                </button>

                                {selectedIds.size > 0 && (
                                    <button
                                        onClick={handleBulkDownload}
                                        disabled={downloading}
                                        className="flex items-center gap-1.5 px-4 py-2 rounded-full text-xs font-semibold transition-all"
                                        style={{
                                            background: "var(--gradient-neon)",
                                            color: "white",
                                            opacity: downloading ? 0.5 : 1,
                                        }}
                                    >
                                        {downloading ? (
                                            <span className="spinner !w-3 !h-3 !border-white/20 !border-t-white"></span>
                                        ) : (
                                            <span className="material-symbols-rounded text-sm">download</span>
                                        )}
                                        Tải {selectedIds.size} ảnh
                                    </button>
                                )}
                            </>
                        )}
                    </div>
                </div>

                {/* Grid */}
                {loading ? (
                    <div className={`grid ${gridClass} gap-4`}>
                        {Array.from({ length: 8 }).map((_, i) => (
                            <div key={i} className="video-card">
                                <div className="aspect-square shimmer" />
                                <div className="p-3">
                                    <div className="h-4 w-3/4 shimmer rounded mb-2" />
                                    <div className="h-3 w-1/2 shimmer rounded" />
                                </div>
                            </div>
                        ))}
                    </div>
                ) : visibleJobs.length === 0 ? (
                    <div className="text-center py-20">
                        <span className="material-symbols-rounded text-5xl mb-4 block" style={{ color: "var(--text-muted)" }}>
                            photo_library
                        </span>
                        <p className="text-lg font-medium" style={{ color: "var(--text-secondary)" }}>
                            {resFilter === "upscaled" ? "Chưa có ảnh upscale nào" : "Chưa có ảnh nào"}
                        </p>
                        {resFilter !== "upscaled" && (
                            <button onClick={() => router.push("/")} className="btn-generate mt-6">
                                Tạo ảnh đầu tiên
                            </button>
                        )}
                    </div>
                ) : (
                    <div className={`grid ${gridClass} gap-4 pb-12`}>
                        {visibleJobs.map((job) => (
                            <ImageCard
                                key={job.id}
                                job={job}
                                selected={selectedIds.has(job.id)}
                                onToggleSelect={() => toggleSelect(job.id)}
                                compact={gridCols >= 6}
                            />
                        ))}
                    </div>
                )}
            </main>
        </div>
    );
}


/* ═══════════════════════════════════════════════════════════════════════════════
 * ImageCard — Image card with checkbox for multi-select
 * ═══════════════════════════════════════════════════════════════════════════════ */
function ImageCard({
    job,
    selected,
    onToggleSelect,
    compact = false,
}: {
    job: HistoryJob;
    selected: boolean;
    onToggleSelect: () => void;
    compact?: boolean;
}) {
    const [hovering, setHovering] = useState(false);
    const [showPreview, setShowPreview] = useState(false);
    const showToast = useStore((s) => s.showToast);

    const imageUrl = job.video_url || job.r2_url;
    const canSelect = job.status === "completed" && !!imageUrl;
    const hasUpscale = !!job.upscale_url;

    const handleDownload = async () => {
        if (!imageUrl) return;
        const dlUrl = imageUrl.startsWith("/") ? `${API_BASE}${imageUrl}` : imageUrl;
        showToast("⏳ Đang tải ảnh...", "info");
        try {
            const resp = await fetch(dlUrl);
            const blob = await resp.blob();
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = `image-${job.id}.png`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(a.href);
            showToast("✅ Đã tải ảnh!", "success");
        } catch {
            window.open(dlUrl, "_blank");
        }
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
                        <p className={`font-medium truncate ${compact ? 'text-xs' : 'text-sm'}`} style={{ color: "var(--text-primary)" }}>{job.prompt}</p>
                        <p className="text-xs mt-1" style={{ color: "var(--error)" }}>{job.error || "Thất bại"}</p>
                        {!compact && <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>Đã hoàn {job.cost.toLocaleString()} credits</p>}
                    </div>
                </div>
            </div>
        );
    }

    if (!imageUrl) {
        return (
            <div className="video-card fade-in">
                <div className="aspect-square shimmer" />
                <div className="p-3">
                    <div className="h-4 w-3/4 shimmer rounded" />
                    <div className="h-3 w-1/2 shimmer rounded mt-2" />
                </div>
            </div>
        );
    }

    return (
        <div
            className="video-card fade-in group relative"
            onMouseEnter={() => setHovering(true)}
            onMouseLeave={() => setHovering(false)}
            style={{
                outline: selected ? "2px solid var(--neon-blue)" : "none",
                outlineOffset: "-2px",
            }}
        >
            {/* Checkbox */}
            {canSelect && (
                <button
                    onClick={(e) => { e.stopPropagation(); onToggleSelect(); }}
                    className="absolute top-2 left-2 z-10 w-6 h-6 rounded flex items-center justify-center transition-all"
                    style={{
                        background: selected ? "var(--neon-blue)" : "rgba(0,0,0,0.5)",
                        border: selected ? "none" : "1.5px solid rgba(255,255,255,0.4)",
                        opacity: hovering || selected ? 1 : 0,
                    }}
                >
                    {selected && (
                        <span className="material-symbols-rounded text-sm text-white">check</span>
                    )}
                </button>
            )}

            {/* Image thumbnail */}
            <div className="relative aspect-square bg-black overflow-hidden cursor-pointer"
                onClick={() => setShowPreview(true)}>
                <img
                    src={job.thumbnail_url || imageUrl}
                    alt={job.prompt}
                    className="w-full h-full object-cover"
                    loading="lazy"
                    decoding="async"
                    fetchPriority="low"
                />

                {/* Hover overlay */}
                <div className={`absolute inset-0 flex items-center justify-center bg-black/40 transition-opacity duration-200 ${hovering ? 'opacity-100' : 'opacity-0'}`}>
                    <button className="w-12 h-12 rounded-full flex items-center justify-center transition-transform hover:scale-110"
                        style={{ background: "rgba(255,255,255,0.15)", backdropFilter: "blur(8px)" }}
                        onClick={(e) => { e.stopPropagation(); setShowPreview(true); }}>
                        <span className="material-symbols-rounded text-2xl text-white">zoom_in</span>
                    </button>
                </div>

                {/* Upscale badge */}
                {hasUpscale && (
                    <div className="absolute top-2 right-2">
                        <span className="badge badge-neon !text-[10px]">HD</span>
                    </div>
                )}
            </div>

            {/* Info */}
            <div className={compact ? "p-2" : "p-3"}>
                <p className={`font-medium truncate mb-1.5 ${compact ? 'text-xs' : 'text-sm'}`} style={{ color: "var(--text-primary)" }}>{job.prompt}</p>

                <div className="flex items-center gap-2 flex-wrap" style={{ minHeight: "28px" }}>
                    <div className="flex items-center gap-2 text-xs shrink-0" style={{ color: "var(--text-muted)" }}>
                        <span>{new Date(job.created_at).toLocaleDateString("vi-VN")}</span>
                        <span>·</span>
                        <span>{job.cost.toLocaleString()} credits</span>
                    </div>

                    {/* Download button — always visible, never overflow hidden */}
                    {!compact && (
                        <button
                            onClick={(e) => { e.stopPropagation(); handleDownload(); }}
                            className="btn-ghost !p-1.5 !rounded-lg ml-auto shrink-0"
                            style={{ color: "var(--neon-blue)" }}
                        >
                            <span className="material-symbols-rounded text-lg">download</span>
                        </button>
                    )}
                </div>
            </div>

            {/* Preview Modal */}
            {showPreview && (
                <VideoPreviewModal job={job} onClose={() => setShowPreview(false)} />
            )}
        </div>
    );
}
