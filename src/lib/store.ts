/**
 * Zustand Store — Global state management
 * Supports batch generation, queue tracking, and media type switching
 */

import { create } from "zustand";

// ── Types ──
export interface UserData {
  user_id: number;
  username: string;
  role: string;
  balance: number;
  credits: number;
  token: string;
}

export interface ActiveJob {
  id: number;
  prompt: string;
  status: string;
  progress: number;
  videoUrl?: string;
  mediaType?: string; // "video" | "image"
  error?: string;
  startedAt: number;
}

export interface HistoryJob {
  id: number;
  prompt: string;
  status: string;
  progress_percent: number;
  model_key?: string;
  media_type?: string;
  video_url?: string;
  r2_url?: string;
  media_id?: string;
  thumbnail_url?: string;
  cost: number;
  error?: string;
  upscale_status?: string;  // "processing" | "completed" | null
  upscale_url?: string;     // URL after upscale done
  upscale_resolution?: string;  // "1K" | "2K" | "4K" | null
  created_at: string;
  started_at?: string;
  finished_at?: string;
}

export interface BatchRow {
  id: string; // temp client ID
  prompt: string;
  jobId?: number;
  status: "idle" | "waiting" | "queued" | "pending" | "processing" | "completed" | "failed";
  progress: number;
  videoUrl?: string;
  error?: string;
  mediaType?: string;
}

export interface UploadedImage {
  id: string;         // unique client ID
  mediaId: string;    // server-side mediaId
  url: string;        // local blob URL or data URL for preview
  name: string;       // original filename
  uploadedAt: number; // timestamp
}

// ── Store ──
interface AppStore {
  // Auth
  user: UserData | null;
  setUser: (user: UserData | null) => void;
  logout: () => void;

  // Active jobs (đang xử lý)
  activeJobs: Map<number, ActiveJob>;
  addActiveJob: (job: ActiveJob) => void;
  updateActiveJob: (id: number, updates: Partial<ActiveJob>) => void;
  removeActiveJob: (id: number) => void;

  // History
  history: HistoryJob[];
  setHistory: (jobs: HistoryJob[]) => void;
  updateHistoryJob: (jobId: number, updates: Partial<HistoryJob>) => void;
  removeJob: (jobId: number) => void;

  // Batch rows for the table UI
  batchRows: BatchRow[];
  setBatchRows: (rows: BatchRow[]) => void;
  addBatchRow: (row: BatchRow) => void;
  updateBatchRow: (id: string, updates: Partial<BatchRow>) => void;
  removeBatchRow: (id: string) => void;
  clearBatchRows: () => void;

  // UI settings
  aspectRatio: string;
  setAspectRatio: (v: string) => void;
  videoModel: string;
  setVideoModel: (v: string) => void;
  imageModel: string;
  setImageModel: (v: string) => void;
  numberOfOutputs: number;
  setNumberOfOutputs: (v: number) => void;
  mediaTab: "video" | "image";
  setMediaTab: (v: "video" | "image") => void;
  videoSubTab: "components" | "keyframes";
  setVideoSubTab: (v: "components" | "keyframes") => void;
  videoDuration: "4" | "6" | "8";
  setVideoDuration: (v: "4" | "6" | "8") => void;
  selectedVoice: string | null;
  setSelectedVoice: (v: string | null) => void;
  startImageId: string | null;
  setStartImageId: (v: string | null) => void;
  startImageUrl: string | null;
  setStartImageUrl: (v: string | null) => void;
  endImageId: string | null;
  setEndImageId: (v: string | null) => void;
  endImageUrl: string | null;
  setEndImageUrl: (v: string | null) => void;

  // Image library
  uploadedImages: UploadedImage[];
  addUploadedImage: (img: UploadedImage) => void;
  removeUploadedImage: (id: string) => void;
  clearUploadedImages: () => void;

  // Queue info
  queueCount: number;
  setQueueCount: (v: number) => void;

  // Refresh callback — set by page to refresh history on completion
  onRefreshHistory: (() => void) | null;
  setOnRefreshHistory: (fn: (() => void) | null) => void;

  // Theme
  theme: "light" | "dark";
  toggleTheme: () => void;

  // Toast
  toast: { message: string; type: "success" | "error" | "info" } | null;
  showToast: (message: string, type?: "success" | "error" | "info") => void;
  clearToast: () => void;

  // Upscale tracking (global so it persists across tab switches)
  upscalingJobIds: Set<number>;
  addUpscalingJob: (jobId: number) => void;
  removeUpscalingJob: (jobId: number) => void;
  isJobUpscaling: (jobId: number) => boolean;
}

export const useStore = create<AppStore>((set, get) => ({
  // ── Auth ──
  user: null,
  setUser: (user) => {
    set({ user });
    if (user) {
      localStorage.setItem("veo3_token", user.token);
      localStorage.setItem("veo3_user", JSON.stringify(user));
      // Load this user's image library
      try {
        const raw = JSON.parse(localStorage.getItem(`veo3_uploaded_images_${user.user_id}`) || "[]") as UploadedImage[];
        const cleaned = raw.filter((img) => !img.url.startsWith("data:") && !img.mediaId.startsWith("data:"));
        set({ uploadedImages: cleaned });
      } catch { set({ uploadedImages: [] }); }
    }
  },
  logout: () => {
    set({ user: null, activeJobs: new Map(), history: [], batchRows: [], uploadedImages: [] });
    localStorage.removeItem("veo3_token");
    localStorage.removeItem("veo3_user");
  },

  // ── Active Jobs ──
  activeJobs: new Map(),
  addActiveJob: (job) => set((s) => {
    const next = new Map(s.activeJobs);
    next.set(job.id, job);
    return { activeJobs: next };
  }),
  updateActiveJob: (id, updates) => set((s) => {
    const next = new Map(s.activeJobs);
    const existing = next.get(id);
    if (existing) next.set(id, { ...existing, ...updates });
    return { activeJobs: next };
  }),
  removeActiveJob: (id) => set((s) => {
    const next = new Map(s.activeJobs);
    next.delete(id);
    return { activeJobs: next };
  }),

  // ── History ──
  history: [],
  setHistory: (jobs) => set({ history: jobs }),
  updateHistoryJob: (jobId, updates) => set((s) => ({
    history: s.history.map((j) => j.id === jobId ? { ...j, ...updates } : j),
  })),
  removeJob: (jobId) => set((s) => ({ history: s.history.filter((j) => j.id !== jobId) })),

  // ── Batch Rows ──
  batchRows: [],
  setBatchRows: (rows) => set({ batchRows: rows }),
  addBatchRow: (row) => set((s) => ({ batchRows: [...s.batchRows, row] })),
  updateBatchRow: (id, updates) => set((s) => ({
    batchRows: s.batchRows.map((r) => r.id === id ? { ...r, ...updates } : r),
  })),
  removeBatchRow: (id) => set((s) => ({
    batchRows: s.batchRows.filter((r) => r.id !== id),
  })),
  clearBatchRows: () => set({ batchRows: [] }),

  // ── Settings ──
  aspectRatio: "16:9",
  setAspectRatio: (v) => set({ aspectRatio: v }),
  videoModel: "veo31_fast_lp",
  setVideoModel: (v) => set({ videoModel: v }),
  imageModel: "nano_banana_pro",
  setImageModel: (v) => set({ imageModel: v }),
  numberOfOutputs: 1,
  setNumberOfOutputs: (v) => set({ numberOfOutputs: v }),
  mediaTab: "video",
  setMediaTab: (v) => set({ mediaTab: v }),
  videoSubTab: "components",
  setVideoSubTab: (v) => set({ videoSubTab: v }),
  videoDuration: "8",
  setVideoDuration: (v) => set({ videoDuration: v }),
  selectedVoice: null,
  setSelectedVoice: (v) => set({ selectedVoice: v }),
  startImageId: null,
  setStartImageId: (v) => set({ startImageId: v }),
  startImageUrl: null,
  setStartImageUrl: (v) => set({ startImageUrl: v }),
  endImageId: null,
  setEndImageId: (v) => set({ endImageId: v }),
  endImageUrl: null,
  setEndImageUrl: (v) => set({ endImageUrl: v }),

  // ── Image Library (per-user via localStorage) ──
  uploadedImages: (() => {
    if (typeof window === "undefined") return [];
    try {
      // Try to get user_id from stored user data for per-user key
      const storedUser = JSON.parse(localStorage.getItem("veo3_user") || "null");
      const userId = storedUser?.user_id;
      const key = userId ? `veo3_uploaded_images_${userId}` : "veo3_uploaded_images";
      const raw = JSON.parse(localStorage.getItem(key) || "[]") as UploadedImage[];
      // Auto-clean: remove entries with data URLs (old format that fills quota)
      const cleaned = raw.filter((img) => !img.url.startsWith("data:") && !img.mediaId.startsWith("data:"));
      if (cleaned.length !== raw.length) {
        localStorage.setItem(key, JSON.stringify(cleaned));
      }
      return cleaned;
    } catch { return []; }
  })(),
  addUploadedImage: (img) => set((s) => {
    const next = [img, ...s.uploadedImages].slice(0, 50); // max 50
    if (typeof window !== "undefined") {
      const storedUser = JSON.parse(localStorage.getItem("veo3_user") || "null");
      const userId = storedUser?.user_id;
      const key = userId ? `veo3_uploaded_images_${userId}` : "veo3_uploaded_images";
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch (e) {
        // localStorage quota exceeded — remove oldest entries and retry
        console.warn("localStorage quota exceeded, cleaning old images...", e);
        const smaller = next.slice(0, 20);
        try { localStorage.setItem(key, JSON.stringify(smaller)); } catch { }
      }
    }
    return { uploadedImages: next };
  }),
  removeUploadedImage: (id) => set((s) => {
    const next = s.uploadedImages.filter((i) => i.id !== id);
    if (typeof window !== "undefined") {
      const storedUser = JSON.parse(localStorage.getItem("veo3_user") || "null");
      const userId = storedUser?.user_id;
      const key = userId ? `veo3_uploaded_images_${userId}` : "veo3_uploaded_images";
      try { localStorage.setItem(key, JSON.stringify(next)); } catch { }
    }
    return { uploadedImages: next };
  }),
  clearUploadedImages: () => {
    if (typeof window !== "undefined") {
      const storedUser = JSON.parse(localStorage.getItem("veo3_user") || "null");
      const userId = storedUser?.user_id;
      const key = userId ? `veo3_uploaded_images_${userId}` : "veo3_uploaded_images";
      localStorage.removeItem(key);
    }
    set({ uploadedImages: [] });
  },

  // ── Queue ──
  queueCount: 0,
  setQueueCount: (v) => set({ queueCount: v }),

  // ── Refresh callback ──
  onRefreshHistory: null,
  setOnRefreshHistory: (fn) => set({ onRefreshHistory: fn }),

  // ── Theme ──
  theme: (typeof window !== "undefined" && localStorage.getItem("veo3_theme") as "light" | "dark") || "light",
  toggleTheme: () => set((s) => {
    const next = s.theme === "dark" ? "light" : "dark";
    if (typeof window !== "undefined") localStorage.setItem("veo3_theme", next);
    return { theme: next };
  }),

  // ── Toast ──
  toast: null,
  showToast: (message, type = "info") => {
    set({ toast: { message, type } });
    // Error toasts stay longer so users can read the details
    const duration = type === "error" ? 8000 : 4000;
    setTimeout(() => set({ toast: null }), duration);
  },
  clearToast: () => set({ toast: null }),

  // ── Upscale tracking ──
  upscalingJobIds: new Set(),
  addUpscalingJob: (jobId) => set((s) => {
    const next = new Set(s.upscalingJobIds);
    next.add(jobId);
    return { upscalingJobIds: next };
  }),
  removeUpscalingJob: (jobId) => set((s) => {
    const next = new Set(s.upscalingJobIds);
    next.delete(jobId);
    return { upscalingJobIds: next };
  }),
  isJobUpscaling: (jobId) => get().upscalingJobIds.has(jobId),
}));
