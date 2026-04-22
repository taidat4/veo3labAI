/**
 * API Docs Page — Trang riêng cho tài liệu API
 */
"use client";
import { useRouter } from "next/navigation";
import { Navbar } from "@/components/Navbar";

export default function DocsPage() {
  const router = useRouter();

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Navbar />
      <main className="pt-20 px-4 sm:px-6 max-w-4xl mx-auto pb-12">

        {/* Back button */}
        <button onClick={() => router.back()}
          className="flex items-center gap-1.5 text-sm font-medium mb-6 transition-colors"
          style={{ color: "var(--text-muted)" }}
          onMouseEnter={e => e.currentTarget.style.color = "var(--neon-blue)"}
          onMouseLeave={e => e.currentTarget.style.color = "var(--text-muted)"}>
          <span className="material-symbols-rounded text-lg">arrow_back</span>
          Quay lại
        </button>

        {/* Header */}
        <div className="flex items-center gap-3 mb-8">
          <span className="material-symbols-rounded text-3xl" style={{ color: "#06b6d4" }}>code</span>
          <div>
            <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>API Documentation</h1>
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>Tài liệu kết nối API Veo3Lab</p>
          </div>
          <span className="badge !text-[10px] ml-2" style={{ background: "rgba(6,182,212,0.15)", color: "#06b6d4" }}>v1</span>
        </div>

        <div className="rounded-xl p-6" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}>

          {/* Base URL */}
          <div className="rounded-lg p-3 mb-5" style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border-subtle)" }}>
            <p className="text-[11px] font-semibold mb-1" style={{ color: "var(--text-muted)" }}>BASE URL</p>
            <code className="text-sm font-mono font-bold" style={{ color: "var(--neon-blue)" }}>
              https://veo3labai.com
            </code>
          </div>

          {/* Architecture note */}
          <div className="rounded-lg p-3 mb-5" style={{ background: "rgba(6,182,212,0.06)", border: "1px solid rgba(6,182,212,0.15)" }}>
            <p className="text-[11px] font-semibold mb-1" style={{ color: "#06b6d4" }}>🏗️ CÁCH HOẠT ĐỘNG</p>
            <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
              Bạn gửi yêu cầu qua API → <strong>Veo3Lab</strong> xử lý tạo video/ảnh → trả kết quả (URL) về cho tool/web của bạn. Mọi xử lý đều diễn ra trên server Veo3Lab, bạn chỉ cần gọi API và poll kết quả.
            </p>
          </div>

          {/* Auth header */}
          <div className="rounded-lg p-3 mb-5" style={{ background: "rgba(168,85,247,0.06)", border: "1px solid rgba(168,85,247,0.15)" }}>
            <p className="text-[11px] font-semibold mb-1" style={{ color: "var(--neon-purple)" }}>🔑 AUTHENTICATION</p>
            <p className="text-xs mb-2" style={{ color: "var(--text-secondary)" }}>Thêm header sau vào mọi request:</p>
            <pre className="text-xs font-mono rounded-md p-2.5 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-primary)" }}>
{`X-API-Key: <YOUR_API_KEY>`}
            </pre>
            <p className="text-[10px] mt-2" style={{ color: "var(--text-muted)" }}>
              API Key được tạo tự động khi đăng ký. Xem và copy tại trang <strong>Hồ sơ</strong>.
            </p>
          </div>

          {/* Endpoints */}
          <div className="space-y-5">

            {/* 1. Generate Video */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#22c55e", color: "white" }}>POST</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/v1/generate</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Tạo video</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`curl -X POST https://veo3labai.com/api/v1/generate \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "prompt": "A cat playing piano in a jazz bar",
    "aspect_ratio": "16:9",
    "video_model": "veo31_fast_lp",
    "number_of_outputs": 1
  }'

# Response:
# {
#   "success": true,
#   "job_id": 123,
#   "job_ids": [123],
#   "cost": 1,
#   "remaining_balance": 99,
#   "message": "Đang xử lý 1 video..."
# }`}
              </pre>
            </div>

            {/* 2. Generate Image */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#22c55e", color: "white" }}>POST</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/v1/generate</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Tạo ảnh</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`curl -X POST https://veo3labai.com/api/v1/generate \\
  -H "X-API-Key: YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "prompt": "A beautiful sunset over mountains",
    "video_model": "imagen_4",
    "aspect_ratio": "1:1",
    "number_of_outputs": 1
  }'`}
              </pre>
            </div>

            {/* 3. Get Job Status */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#3b82f6", color: "white" }}>GET</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/v1/jobs/{"{job_id}"}</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Kiểm tra trạng thái</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`curl https://veo3labai.com/api/v1/jobs/123 \\
  -H "X-API-Key: YOUR_API_KEY"

# Response:
# {
#   "id": 123,
#   "status": "completed",
#   "prompt": "A cat playing piano",
#   "media_type": "video",
#   "video_url": "https://...",
#   "cost": 1,
#   "progress_percent": 100,
#   "created_at": "2026-04-23T00:00:00",
#   "finished_at": "2026-04-23T00:02:30"
# }`}
              </pre>
            </div>

            {/* 4. List Jobs */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#3b82f6", color: "white" }}>GET</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/v1/jobs?limit=50&offset=0</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Danh sách jobs</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`curl "https://veo3labai.com/api/v1/jobs?limit=50&offset=0" \\
  -H "X-API-Key: YOUR_API_KEY"

# Response:
# {
#   "jobs": [ { "id": 123, "status": "completed", "video_url": "...", ... } ],
#   "total": 42
# }`}
              </pre>
            </div>

            {/* 5. Account Info */}
            <div className="rounded-lg overflow-hidden" style={{ border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold" style={{ background: "#3b82f6", color: "white" }}>GET</span>
                <code className="text-xs font-mono font-semibold" style={{ color: "var(--text-primary)" }}>/api/v1/me</code>
                <span className="text-[10px] ml-auto" style={{ color: "var(--text-muted)" }}>Thông tin tài khoản</span>
              </div>
              <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`curl https://veo3labai.com/api/v1/me \\
  -H "X-API-Key: YOUR_API_KEY"

# Response:
# {
#   "user_id": 1,
#   "username": "user123",
#   "balance": 50000,
#   "credits": 100,
#   "role": "user"
# }`}
              </pre>
            </div>
          </div>

          {/* JavaScript Example */}
          <div className="mt-6 rounded-lg overflow-hidden" style={{ border: "1px solid rgba(99,102,241,0.3)" }}>
            <div className="flex items-center gap-2 px-4 py-2.5" style={{ background: "rgba(99,102,241,0.08)" }}>
              <span className="material-symbols-rounded text-sm" style={{ color: "var(--neon-blue)" }}>javascript</span>
              <span className="text-xs font-semibold" style={{ color: "var(--neon-blue)" }}>JavaScript / Node.js Example</span>
            </div>
            <pre className="text-[11px] font-mono p-4 overflow-x-auto" style={{ background: "var(--bg-primary)", color: "var(--text-secondary)" }}>
{`const API_KEY = "YOUR_API_KEY";
const BASE = "https://veo3labai.com";

// 1. Tạo video
const res = await fetch(\`\${BASE}/api/v1/generate\`, {
  method: "POST",
  headers: {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    prompt: "A cat playing piano in a jazz bar",
    aspect_ratio: "16:9",
    video_model: "veo31_fast_lp"
  })
});
const { job_id } = await res.json();

// 2. Poll trạng thái (5-10s interval)
const poll = async () => {
  const r = await fetch(\`\${BASE}/api/v1/jobs/\${job_id}\`, {
    headers: { "X-API-Key": API_KEY }
  });
  const job = await r.json();
  
  if (job.status === "completed") {
    console.log("✅ Video URL:", job.video_url);
    // Dùng video_url này trong tool/web của bạn
    return;
  }
  if (job.status === "failed") {
    console.log("❌ Error:", job.error);
    return;
  }
  
  console.log(\`⏳ \${job.progress_percent}% ...\`);
  setTimeout(poll, 5000);
};
poll();`}
            </pre>
          </div>

          {/* Models table */}
          <div className="mt-6">
            <p className="text-[11px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>Models có sẵn</p>
            <div className="overflow-x-auto rounded-lg" style={{ border: "1px solid var(--border-subtle)" }}>
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ background: "var(--bg-tertiary)" }}>
                    <th className="text-left px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Model Key</th>
                    <th className="text-left px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Loại</th>
                    <th className="text-left px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Mô tả</th>
                    <th className="text-right px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Credit</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { key: "veo31_fast_lp", type: "🎬 Video", desc: "Veo 3.1 — Quality", credit: "1" },
                    { key: "imagen_4", type: "🖼️ Image", desc: "Imagen 4 (cao cấp)", credit: "1" },
                    { key: "nano_banana_pro", type: "🖼️ Image", desc: "Nano Banana Pro", credit: "1" },
                    { key: "nano_banana_2", type: "🖼️ Image", desc: "Nano Banana 2", credit: "1" },
                  ].map((m, i) => (
                    <tr key={i} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                      <td className="px-4 py-2.5 font-mono font-semibold" style={{ color: "var(--neon-blue)" }}>{m.key}</td>
                      <td className="px-4 py-2.5" style={{ color: "var(--text-secondary)" }}>{m.type}</td>
                      <td className="px-4 py-2.5" style={{ color: "var(--text-secondary)" }}>{m.desc}</td>
                      <td className="px-4 py-2.5 text-right font-semibold" style={{ color: "var(--neon-purple)" }}>{m.credit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Parameters table */}
          <div className="mt-6">
            <p className="text-[11px] font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>Parameters cho /generate</p>
            <div className="overflow-x-auto rounded-lg" style={{ border: "1px solid var(--border-subtle)" }}>
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ background: "var(--bg-tertiary)" }}>
                    <th className="text-left px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Field</th>
                    <th className="text-left px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Type</th>
                    <th className="text-left px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Mô tả</th>
                    <th className="text-left px-4 py-2 font-semibold" style={{ color: "var(--text-muted)" }}>Default</th>
                  </tr>
                </thead>
                <tbody>
                  {[
                    { field: "prompt", type: "string", desc: "Nội dung mô tả (bắt buộc, tối đa 5000 ký tự)", def: "—" },
                    { field: "video_model", type: "string", desc: "Model key (xem bảng trên)", def: "veo31_fast_lp" },
                    { field: "aspect_ratio", type: "string", desc: "16:9 | 9:16 | 1:1 | 4:3 | 3:4", def: "16:9" },
                    { field: "number_of_outputs", type: "int", desc: "Số lượng (1-4)", def: "1" },
                  ].map((p, i) => (
                    <tr key={i} style={{ borderTop: "1px solid var(--border-subtle)" }}>
                      <td className="px-4 py-2.5 font-mono font-semibold" style={{ color: "var(--neon-blue)" }}>{p.field}</td>
                      <td className="px-4 py-2.5 font-mono" style={{ color: "var(--text-muted)" }}>{p.type}</td>
                      <td className="px-4 py-2.5" style={{ color: "var(--text-secondary)" }}>{p.desc}</td>
                      <td className="px-4 py-2.5 font-mono" style={{ color: "var(--text-muted)" }}>{p.def}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Video output info */}
          <div className="mt-6 rounded-lg p-3" style={{ background: "rgba(99,102,241,0.06)", border: "1px solid rgba(99,102,241,0.15)" }}>
            <p className="text-[11px] font-semibold mb-2" style={{ color: "var(--neon-blue)" }}>📹 VIDEO OUTPUT</p>
            <ul className="text-xs space-y-1" style={{ color: "var(--text-secondary)" }}>
              <li>• <strong>Độ phân giải:</strong> 720p (mặc định), hỗ trợ upscale lên <strong>1080p</strong></li>
              <li>• <strong>Thời lượng:</strong> 4s, 6s, hoặc 8s</li>
              <li>• <strong>Format:</strong> MP4</li>
              <li>• <strong>Tỉ lệ:</strong> 16:9 (ngang) hoặc 9:16 (dọc)</li>
            </ul>
          </div>

          {/* Status flow */}
          <div className="mt-5 rounded-lg p-3" style={{ background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.15)" }}>
            <p className="text-[11px] font-semibold mb-2" style={{ color: "#22c55e" }}>📊 WORKFLOW</p>
            <div className="text-xs space-y-1" style={{ color: "var(--text-secondary)" }}>
              <p><strong>1.</strong> Gọi <code>POST /api/v1/generate</code> → nhận <code>job_id</code></p>
              <p><strong>2.</strong> Poll <code>GET /api/v1/jobs/{"{job_id}"}</code> mỗi 5-10 giây</p>
              <p><strong>3.</strong> Khi <code>status = &quot;completed&quot;</code> → lấy <code>video_url</code> để download hoặc hiển thị</p>
            </div>
            <p className="text-[10px] mt-2" style={{ color: "var(--text-muted)" }}>
              Status flow: queued → pending → processing → completed / failed. Video thường mất 1-3 phút, ảnh 10-30 giây.
            </p>
          </div>

          {/* Rate limits note */}
          <div className="mt-5 rounded-lg p-3" style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.15)" }}>
            <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
              <span className="material-symbols-rounded text-xs align-middle mr-1" style={{ color: "#f59e0b" }}>warning</span>
              <strong>Rate Limit:</strong> Tối đa 8 job đồng thời. Jobs vượt quá sẽ tự động vào hàng chờ và chạy khi có slot trống.
            </p>
          </div>
        </div>

      </main>
    </div>
  );
}
