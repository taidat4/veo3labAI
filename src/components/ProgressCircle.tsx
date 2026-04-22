/**
 * ProgressCircle — Circular progress indicator
 * Hiển thị % tiến độ đẹp + neon gradient
 * Auto-increment: UI tự tăng dần giữa các backend update để progress không bị đứng
 */
"use client";

import { useEffect, useRef, useState } from "react";

export function ProgressCircle({ percent, size = 80 }: { percent: number; size?: number }) {
  const strokeWidth = 4;
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;

  // Smooth display percent — auto-increments between real updates
  const [displayPercent, setDisplayPercent] = useState(percent);
  const realPercentRef = useRef(percent);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    realPercentRef.current = percent;
    // If real percent jumped ahead, snap to it
    if (percent > displayPercent) {
      setDisplayPercent(percent);
    }
  }, [percent]);

  useEffect(() => {
    // Auto-increment: every 2s, add 1% if not at 95% and not already at real percent
    timerRef.current = setInterval(() => {
      setDisplayPercent((prev) => {
        const real = realPercentRef.current;
        // Don't go past 95% (wait for real 100% from backend)
        if (prev >= 95) return prev;
        // If real has caught up or surpassed, don't auto-increment
        if (real >= prev + 2) return real;
        // Auto-increment by 1
        return prev + 1;
      });
    }, 2000);

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const offset = circumference - (displayPercent / 100) * circumference;

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={size} height={size} className="progress-ring">
        <defs>
          <linearGradient id="neonGradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#6366f1" />
            <stop offset="50%" stopColor="#a855f7" />
            <stop offset="100%" stopColor="#ec4899" />
          </linearGradient>
        </defs>
        {/* Background circle */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.06)"
          strokeWidth={strokeWidth}
        />
        {/* Progress circle — smooth CSS transition */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="url(#neonGradient)"
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className="progress-ring-circle"
          style={{ transition: "stroke-dashoffset 1.5s ease-out" }}
        />
      </svg>
      {/* Center text */}
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-lg font-bold gradient-text">{displayPercent}%</span>
      </div>
    </div>
  );
}


/**
 * ActiveJobCard — Job đang xử lý với progress circle
 */
export function ActiveJobCard({ job, index }: { job: { id: number; prompt: string; status: string; progress: number; startedAt: number; mediaType?: string; error?: string }; index?: number }) {
  const elapsed = Math.floor((Date.now() - job.startedAt) / 1000);
  const isImage = job.mediaType === "image";
  const isFailed = job.status === "failed";
  const estimatedTotal = isImage ? 30 : 120;
  const remaining = Math.max(0, estimatedTotal - elapsed);
  const mins = Math.floor(remaining / 60);
  const secs = remaining % 60;

  // Parse error for user-friendly display
  const getErrorDisplay = (error?: string): string => {
    if (!error) return "Đã xảy ra lỗi";
    if (error.includes("IP_FILTER")) return "⛔ Bị chặn IP — thử lại sau";
    if (error.includes("POLICY") || error.includes("policy")) return "⛔ Vi phạm chính sách nội dung";
    if (error.includes("INVALID_ARGUMENT")) return "⛔ Yêu cầu không hợp lệ";
    if (error.includes("timeout") || error.includes("Timeout")) return "⏰ Quá thời gian chờ";
    if (error.includes("Token expired") || error.includes("UNAUTHENTICATED")) return "🔑 Token hết hạn";
    if (error.includes("rate") || error.includes("Rate")) return "⚡ Bị giới hạn tốc độ";
    if (error.includes("Server restarted")) return "🔄 Server đã restart";
    return error.length > 60 ? error.slice(0, 60) + "..." : error;
  };

  const statusLabels: Record<string, string> = {
    waiting: "Đang chờ slot...",
    queued: "Đang chờ trong queue...",
    pending: "Đang chuẩn bị...",
    processing: isImage ? "Đang tạo ảnh..." : "Đang tạo video...",
    failed: "❌ Thất bại",
  };

  return (
    <div className={`glass-card p-5 fade-in ${isFailed ? "" : "glow-pulse"}`} style={isFailed ? { borderColor: "var(--error-color, #ef4444)", opacity: 0.8 } : {}}>
      <div className="flex items-center gap-5">
        {isFailed ? (
          <div className="relative inline-flex items-center justify-center" style={{ width: 72, height: 72 }}>
            <span className="material-symbols-rounded text-3xl" style={{ color: "var(--error-color, #ef4444)" }}>error</span>
          </div>
        ) : (
          <ProgressCircle percent={Math.max(job.progress, 3)} size={72} />
        )}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate mb-1" style={{ color: "var(--text-primary)" }}>
            {job.prompt}
          </p>
          <p className="text-xs mb-2" style={{ color: isFailed ? "var(--error-color, #ef4444)" : "var(--neon-blue)" }}>
            {isFailed ? getErrorDisplay(job.error) : (statusLabels[job.status] || "Đang xử lý...")}
          </p>
          <div className="flex items-center gap-3 text-xs" style={{ color: "var(--text-muted)" }}>
            {!isFailed && <span>⏱ ~{mins}:{secs.toString().padStart(2, "0")} còn lại</span>}
            {!isFailed && <span>•</span>}
            <span>job #{index ?? job.id}</span>
          </div>
          {/* Progress bar — smooth CSS transition */}
          {!isFailed && (
            <div className="progress-bar mt-2">
              <div className="progress-fill" style={{ width: `${Math.max(job.progress, 5)}%`, transition: "width 1.5s ease-out" }} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
