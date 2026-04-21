/**
 * API Client — Kết nối FastAPI backend
 * 2 hệ thống auth tách biệt:
 * - User: JWT token (localStorage veo3_token)
 * - Admin: Secret key → Admin token (sessionStorage admin_token)
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "";

interface RequestOptions {
  method?: string;
  body?: any;
  headers?: Record<string, string>;
  useAdminAuth?: boolean; // true = use admin token instead of user token
}

async function request<T = any>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...opts.headers,
  };

  if (opts.useAdminAuth) {
    // Admin routes: use admin token from sessionStorage (set after secret key verification)
    const adminToken = typeof window !== "undefined" ? sessionStorage.getItem("admin_token") : "";
    if (adminToken) headers["X-Admin-Key"] = adminToken;
  } else if (typeof window !== "undefined") {
    const token = localStorage.getItem("veo3_token");
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method: opts.method || "GET",
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });

  if (res.status === 401) {
    const isAuthRequest = path.includes('/auth');
    if (typeof window !== "undefined" && !isAuthRequest) {
      if (opts.useAdminAuth) {
        // Admin auth failed — don't redirect, let admin page handle it
        throw new Error("Admin session expired");
      } else {
        // Token expired → auto logout and redirect to login
        localStorage.removeItem("veo3_token");
        localStorage.removeItem("veo3_user");
        if (!window.location.pathname.includes('/login')) {
          window.location.href = "/login";
        }
      }
    }
    throw new Error("Unauthorized");
  }

  // Handle non-JSON responses (e.g. 500 Internal Server Error)
  const text = await res.text();
  let data: any;
  try {
    data = JSON.parse(text);
  } catch {
    if (!res.ok) throw new Error(text || `Server error (${res.status})`);
    throw new Error("Invalid JSON response from server");
  }
  if (!res.ok) throw new Error(data.detail || data.error || "Request failed");
  return data;
}

// ═══════════════════════════════════════════════════════════════════════════════
// USER API
// ═══════════════════════════════════════════════════════════════════════════════

export const api = {

  // ── Auth (User) ──
  login: (username: string, password: string) =>
    request("/api/auth/login", { method: "POST", body: { username, password } }),

  register: (username: string, password: string) =>
    request("/api/auth/register", { method: "POST", body: { username, password } }),

  // ── Generate (single) ──
  generate: (data: {
    prompt: string;
    aspect_ratio?: string;
    number_of_outputs?: number;
    video_model?: string;
    resolution?: string;
  }) => request("/api/generate", { method: "POST", body: data }),

  // ── Generate (bulk) ──
  generateBulk: (data: {
    prompts: string[];
    aspect_ratio?: string;
    number_of_outputs?: number;
    video_model?: string;
    resolution?: string;
  }) => request("/api/generate/bulk", { method: "POST", body: data }),

  // ── Jobs ──
  getJob: (jobId: number) => request(`/api/job/${jobId}`),
  getJobs: (limit = 50, offset = 0) =>
    request(`/api/jobs?limit=${limit}&offset=${offset}`),
  deleteJob: (jobId: number) =>
    request(`/api/job/${jobId}`, { method: "DELETE" }),

  // ── Models ──
  getModels: () => request("/api/models"),

  // ── Video/Image ──
  getVideoUrl: (jobId: number) => `${API_BASE}/api/proxy/video/${jobId}`,
  getDownloadUrl: (jobId: number, quality = "720") => {
    const token = typeof window !== "undefined" ? localStorage.getItem("veo3_token") : "";
    return `${API_BASE}/api/download/${jobId}?quality=${quality}&token=${token || ""}`;
  },

  // ── Upscale (720p → 1080p) ──
  triggerUpscale: (jobId: number) =>
    request(`/api/upscale/${jobId}`, { method: "POST" }),
  upscaleVideo: (jobId: number) =>
    request(`/api/upscale/${jobId}`, { method: "POST" }),
  getUpscaleStatus: (jobId: number) =>
    request(`/api/upscale/${jobId}/status`),

  // ── Upscale Image (1K / 2K / 4K) ──
  upscaleImage: (jobId: number, resolution: string) =>
    request(`/api/upscale-image/${jobId}`, { method: "POST", body: { resolution } }),

  // ── Queue ──
  getQueueStatus: () => request("/api/queue-status"),

  // ── Profile ──
  getMe: () => request("/api/auth/me"),
  generateApiKey: () => request("/api/auth/me/generate-api-key", { method: "POST" }),
  changePassword: (current_password: string, new_password: string) =>
    request("/api/auth/me/change-password", { method: "POST", body: { current_password, new_password } }),

  // ── Deposit / Payment ──
  requestDeposit: (amount: number) =>
    request("/api/deposit/request", { method: "POST", body: { amount } }),
  verifyDeposit: (token: string) =>
    request(`/api/deposit/verify/${token}`, { method: "POST" }),
  getDepositStatus: (token: string) =>
    request(`/api/deposit/status/${token}`),

  // ── Plans / Pricing ──
  getPlans: () => request("/api/plans"),
};

// ═══════════════════════════════════════════════════════════════════════════════
// ADMIN API (Hoàn toàn tách biệt — dùng admin token từ sessionStorage)
// ═══════════════════════════════════════════════════════════════════════════════

export const adminApi = {
  // ── Admin Auth (Secret Key) ──
  authenticate: (secretKey: string) =>
    request("/api/admin/auth", { method: "POST", body: { secret_key: secretKey } }),

  // ── Dashboard ──
  getPool: () => request("/api/admin/pool", { useAdminAuth: true }),
  getDashboard: () => request("/api/admin/dashboard", { useAdminAuth: true }),

  // ── Accounts ──
  addAccount: (data: { email: string; password: string; totp_secret?: string; bearer_token?: string; proxy_url?: string; flow_project_url?: string }) =>
    request("/api/admin/accounts", { method: "POST", body: data, useAdminAuth: true }),
  updateToken: (accountId: number, bearer_token: string, expires_in_minutes = 180) =>
    request(`/api/admin/accounts/${accountId}/token`, {
      method: "PUT", body: { bearer_token, expires_in_minutes }, useAdminAuth: true,
    }),
  deleteAccount: (accountId: number) =>
    request(`/api/admin/accounts/${accountId}`, { method: "DELETE", useAdminAuth: true }),
  healthCheck: (accountId: number) =>
    request(`/api/admin/accounts/${accountId}/health-check`, { method: "POST", useAdminAuth: true }),
  resetAccount: (accountId: number) =>
    request(`/api/admin/accounts/${accountId}/reset`, { method: "POST", useAdminAuth: true }),
  extractToken: (accountId: number) =>
    request(`/api/admin/accounts/${accountId}/extract-token`, { method: "POST", useAdminAuth: true }),
  updateAccount: (accountId: number, data: Record<string, any>) =>
    request(`/api/admin/accounts/${accountId}`, { method: "PUT", body: data, useAdminAuth: true }),
  getAccountStats: (accountId: number) =>
    request(`/api/admin/accounts/${accountId}/stats`, { useAdminAuth: true }),
  toggleAccount: (accountId: number) =>
    request(`/api/admin/accounts/${accountId}/toggle`, { method: "PUT", useAdminAuth: true }),

  // ── Users ──
  getUsers: (limit = 50, offset = 0) =>
    request(`/api/admin/users?limit=${limit}&offset=${offset}`, { useAdminAuth: true }),
  toggleBanUser: (userId: number) =>
    request(`/api/admin/users/${userId}/ban`, { method: "PUT", useAdminAuth: true }),
  adjustBalance: (userId: number, amount: number, reason: string) =>
    request(`/api/admin/users/${userId}/balance`, {
      method: "POST", body: { amount, reason }, useAdminAuth: true,
    }),
  updateUserRole: (userId: number, role: string) =>
    request(`/api/admin/users/${userId}/role`, {
      method: "PUT", body: { role }, useAdminAuth: true,
    }),

  // ── Plans ──
  getPlans: () => request("/api/admin/plans", { useAdminAuth: true }),
  createPlan: (data: any) =>
    request("/api/admin/plans", { method: "POST", body: data, useAdminAuth: true }),
  updatePlan: (planId: number, data: any) =>
    request(`/api/admin/plans/${planId}`, { method: "PUT", body: data, useAdminAuth: true }),
  deletePlan: (planId: number) =>
    request(`/api/admin/plans/${planId}`, { method: "DELETE", useAdminAuth: true }),

  // ── Settings ──
  getSettings: () => request("/api/admin/settings", { useAdminAuth: true }),
  updateSettings: (settings: Record<string, string>) =>
    request("/api/admin/settings", { method: "PUT", body: { settings }, useAdminAuth: true }),

  // ── NanoExt ──
  getExtConfig: () => request("/api/admin/nano-ext/config", { useAdminAuth: true }),
  updateExtConfig: (data: { enabled?: boolean; interval_minutes?: number }) =>
    request("/api/admin/nano-ext/config", { method: "PUT", body: data, useAdminAuth: true }),
  getTokenLog: () => request("/api/admin/nano-ext/token-log", { useAdminAuth: true }),

  // ── Logs ──
  getLogs: (type: "jobs" | "balance" | "errors" = "jobs", limit = 50) =>
    request(`/api/admin/logs?type=${type}&limit=${limit}`, { useAdminAuth: true }),
};

// ── WebSocket URL ──
export function getWSUrl(userId: number, token: string): string {
  if (API_BASE) {
    // Dev mode: API_BASE = "http://localhost:8000"
    const wsBase = API_BASE.replace("http", "ws");
    return `${wsBase}/ws/progress/${userId}?token=${token}`;
  }
  // Production: derive from current page URL
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/progress/${userId}?token=${token}`;
}
