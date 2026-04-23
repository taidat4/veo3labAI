/**
 * useWebSocket — Hook cho realtime progress updates
 */

"use client";
import { useEffect, useRef, useCallback } from "react";
import { useStore } from "@/lib/store";
import { getWSUrl } from "@/lib/api";

export function useWebSocket() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<NodeJS.Timeout | null>(null);
  const user = useStore((s) => s.user);
  const updateActiveJob = useStore((s) => s.updateActiveJob);
  const removeActiveJob = useStore((s) => s.removeActiveJob);
  const showToast = useStore((s) => s.showToast);

  const connect = useCallback(() => {
    if (!user) return;

    const url = getWSUrl(user.user_id, user.token);

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("[WS] Connected");
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);

          if (data.type === "progress") {
            updateActiveJob(data.job_id, {
              progress: data.progress_percent,
              status: data.status,
            });
          } else if (data.type === "completed") {
            const activeJob = useStore.getState().activeJobs.get(data.job_id);
            const isImg = activeJob?.mediaType === "image";
            updateActiveJob(data.job_id, {
              progress: 100,
              status: "completed",
              videoUrl: data.video_url,
            });
            showToast(isImg ? "🎉 Ảnh đã tạo xong!" : "🎉 Video đã tạo xong!", "success");
            // Refresh history immediately so completed media shows up
            const refreshFn = useStore.getState().onRefreshHistory;
            if (refreshFn) refreshFn();
            // Remove active job card after animation
            setTimeout(() => removeActiveJob(data.job_id), 2000);
          } else if (data.type === "failed") {
            const failedJob = useStore.getState().activeJobs.get(data.job_id);
            const isImgFail = failedJob?.mediaType === "image";
            updateActiveJob(data.job_id, {
              status: "failed",
              error: data.error,
            });
            const errMsg = data.error || (isImgFail ? "Tạo ảnh thất bại" : "Tạo video thất bại");
            const promptSnip = failedJob?.prompt ? ` — "${failedJob.prompt.slice(0, 40)}..."` : "";
            showToast(`❌ ${errMsg}${promptSnip}`, "error");
            // Refresh history so failed job shows in history
            const refreshFn2 = useStore.getState().onRefreshHistory;
            if (refreshFn2) refreshFn2();
            // Keep failed card visible for 15s so user can read the error
            setTimeout(() => removeActiveJob(data.job_id), 15000);
          }
        } catch (e) {
          console.error("[WS] Parse error:", e);
        }
      };

      ws.onclose = () => {
        console.log("[WS] Disconnected, reconnecting in 3s...");
        reconnectTimer.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    } catch {
      reconnectTimer.current = setTimeout(connect, 5000);
    }
  }, [user, updateActiveJob, removeActiveJob, showToast]);

  useEffect(() => {
    connect();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, [connect]);

  // Ping/keepalive
  useEffect(() => {
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send("ping");
      }
    }, 30000);
    return () => clearInterval(pingInterval);
  }, []);
}
