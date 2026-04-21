/**
 * Deposit Page — Nạp tiền qua MBBank QR
 * User nạp VNĐ vào số dư → dùng số dư mua gói đăng ký
 */
"use client";
import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { useStore } from "@/lib/store";
import { Navbar } from "@/components/Navbar";
import { Toast } from "@/components/Toast";

const PRESET_AMOUNTS = [
  { amount: 50000, label: "50K" },
  { amount: 100000, label: "100K" },
  { amount: 200000, label: "200K" },
  { amount: 500000, label: "500K" },
  { amount: 1000000, label: "1M" },
  { amount: 2000000, label: "2M" },
];

type DepositState = "select" | "qr" | "checking" | "success";

interface DepositInfo {
  token: string;
  amount: number;
  credits: number;
  qr_url: string;
  bank_name: string;
  bank_account: string;
  transfer_content: string;
  expires_at: string;
}

export default function DepositPage() {
  const router = useRouter();
  const user = useStore((s) => s.user);
  const showToast = useStore((s) => s.showToast);
  const setUser = useStore((s) => s.setUser);

  const [state, setState] = useState<DepositState>("select");
  const [selectedAmount, setSelectedAmount] = useState(100000);
  const [customAmount, setCustomAmount] = useState("");
  const [loading, setLoading] = useState(false);
  const [depositInfo, setDepositInfo] = useState<DepositInfo | null>(null);
  const [countdown, setCountdown] = useState(0);
  const [checkCount, setCheckCount] = useState(0);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  // Auth check
  useEffect(() => {
    const stored = localStorage.getItem("veo3_user");
    const token = localStorage.getItem("veo3_token");
    if (!stored || !token) {
      router.push("/login");
    }
  }, [router]);

  // Countdown timer
  useEffect(() => {
    if (state !== "qr" && state !== "checking") return;
    if (!depositInfo?.expires_at) return;

    const interval = setInterval(() => {
      const remaining = Math.max(0, Math.floor((new Date(depositInfo.expires_at).getTime() - Date.now()) / 1000));
      setCountdown(remaining);
      if (remaining <= 0) {
        setState("select");
        setDepositInfo(null);
        showToast("⏰ Mã nạp tiền đã hết hạn!", "error");
        clearInterval(interval);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [state, depositInfo, showToast]);

  // Auto-poll verify — CHỈ khi user đã bấm "Đã chuyển khoản"
  // Poll mỗi 3s, max 200 lần (10 phút)
  const MAX_CHECK_ATTEMPTS = 200;
  useEffect(() => {
    if (state !== "checking" || !depositInfo?.token) return;

    pollRef.current = setInterval(async () => {
      setCheckCount(prev => {
        if (prev >= MAX_CHECK_ATTEMPTS) {
          if (pollRef.current) clearInterval(pollRef.current);
          showToast("⏰ Đã kiểm tra 10 phút. Vui lòng bấm 'Đã chuyển khoản' lại nếu chưa nhận được.", "error");
          setState("qr");
          return 0;
        }
        return prev + 1;
      });

      try {
        const token = localStorage.getItem("veo3_token");
        const res = await fetch(`/api/deposit/verify/${depositInfo.token}`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();

        if (data.status === "completed") {
          setState("success");
          showToast(`🎉 Nạp thành công! +${data.amount?.toLocaleString()}đ`, "success");
          // Update user balance
          if (data.new_balance != null) {
            const stored = localStorage.getItem("veo3_user");
            if (stored) {
              const u = JSON.parse(stored);
              u.balance = data.new_balance;
              localStorage.setItem("veo3_user", JSON.stringify(u));
              setUser({ ...u, token });
            }
          }
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch {}
    }, 3000);

    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [state, depositInfo, showToast, setUser]);

  const handleCreateDeposit = async () => {
    const amount = customAmount ? parseInt(customAmount) : selectedAmount;
    if (amount < 10000) {
      showToast("Số tiền tối thiểu 10,000đ", "error");
      return;
    }

    setLoading(true);
    try {
      const token = localStorage.getItem("veo3_token");
      const res = await fetch("/api/deposit/request", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ amount }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Lỗi tạo yêu cầu nạp");

      setDepositInfo(data);
      setState("qr");
    } catch (e: any) {
      showToast(e.message || "Lỗi tạo yêu cầu nạp", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleStartCheck = () => {
    setState("checking");
    setCheckCount(0);
  };

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  const activeAmount = customAmount ? parseInt(customAmount) || 0 : selectedAmount;

  if (!user) return null;

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Toast />
      <Navbar />

      <main style={{ paddingTop: 88, paddingBottom: 40 }} className="max-w-2xl mx-auto px-5">
        {/* Page title */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-4"
            style={{ background: "linear-gradient(135deg, #10b981, #059669)", boxShadow: "0 8px 32px rgba(16,185,129,0.3)" }}>
            <span className="material-symbols-rounded text-3xl text-white">account_balance_wallet</span>
          </div>
          <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>Nạp tiền</h1>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            Chuyển khoản MBBank — Số dư cộng tự động
          </p>
        </div>

        {/* Current balance */}
        <div className="rounded-xl p-4 mb-6 flex items-center justify-between"
          style={{ background: "linear-gradient(135deg, rgba(99,102,241,0.1), rgba(168,85,247,0.1))", border: "1px solid rgba(99,102,241,0.2)" }}>
          <div className="flex items-center gap-3">
            <span className="material-symbols-rounded text-2xl" style={{ color: "var(--neon-blue)" }}>account_balance_wallet</span>
            <div>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>Số dư hiện tại</p>
              <p className="text-xl font-bold" style={{ color: "var(--neon-blue)" }}>{(user.balance ?? 0).toLocaleString()}đ</p>
            </div>
          </div>
          <button onClick={() => router.push("/plans")}
            className="text-xs px-3 py-1.5 rounded-lg font-medium transition-all"
            style={{ background: "var(--bg-tertiary)", color: "var(--neon-purple)", border: "1px solid var(--border-subtle)" }}
            onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg-hover)"}
            onMouseLeave={(e) => e.currentTarget.style.background = "var(--bg-tertiary)"}>
            Mua gói →
          </button>
        </div>

        {/* ═══ STATE: SELECT AMOUNT ═══ */}
        {state === "select" && (
          <div className="glass-card p-6" style={{ boxShadow: "var(--shadow-card)" }}>
            <h2 className="text-sm font-semibold mb-4 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <span className="material-symbols-rounded text-lg" style={{ color: "#10b981" }}>payments</span>
              Chọn số tiền nạp
            </h2>

            {/* Preset amounts grid */}
            <div className="grid grid-cols-3 gap-3 mb-5">
              {PRESET_AMOUNTS.map((p) => (
                <button
                  key={p.amount}
                  onClick={() => { setSelectedAmount(p.amount); setCustomAmount(""); }}
                  className="rounded-xl p-3 text-center transition-all"
                  style={{
                    background: selectedAmount === p.amount && !customAmount
                      ? "linear-gradient(135deg, #10b981, #059669)"
                      : "var(--bg-tertiary)",
                    color: selectedAmount === p.amount && !customAmount ? "white" : "var(--text-primary)",
                    border: `2px solid ${selectedAmount === p.amount && !customAmount ? "#10b981" : "var(--border-subtle)"}`,
                    transform: selectedAmount === p.amount && !customAmount ? "scale(1.03)" : "scale(1)",
                  }}
                >
                  <p className="text-lg font-bold">{p.label}</p>
                  <p className="text-xs opacity-75">{p.amount.toLocaleString()}đ</p>
                </button>
              ))}
            </div>

            {/* Custom amount */}
            <div className="mb-5">
              <label className="text-xs font-semibold block mb-2" style={{ color: "var(--text-muted)" }}>
                Hoặc nhập số tiền tùy chỉnh
              </label>
              <div className="flex items-center gap-3">
                <input
                  type="number"
                  value={customAmount}
                  onChange={(e) => setCustomAmount(e.target.value)}
                  placeholder="Nhập số tiền..."
                  className="input-field flex-1"
                  min={10000}
                  step={10000}
                />
                <span className="text-sm font-medium" style={{ color: "var(--text-muted)" }}>VNĐ</span>
              </div>
            </div>

            {/* Summary */}
            <div className="rounded-xl p-4 mb-5" style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border-subtle)" }}>
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Số tiền nạp</span>
                <span className="text-lg font-bold" style={{ color: "#10b981" }}>+{activeAmount.toLocaleString()}đ</span>
              </div>
            </div>

            {/* CTA */}
            <button
              onClick={handleCreateDeposit}
              disabled={loading || activeAmount < 10000}
              className="w-full py-3.5 rounded-xl text-white font-semibold text-sm flex items-center justify-center gap-2 transition-all"
              style={{
                background: activeAmount >= 10000 ? "linear-gradient(135deg, #10b981, #059669)" : "var(--bg-tertiary)",
                color: activeAmount >= 10000 ? "white" : "var(--text-muted)",
                opacity: loading ? 0.7 : 1,
                boxShadow: activeAmount >= 10000 ? "0 4px 20px rgba(16,185,129,0.3)" : "none",
              }}
            >
              {loading
                ? <span className="spinner !w-5 !h-5 !border-white/20 !border-t-white"></span>
                : <span className="material-symbols-rounded text-lg">qr_code_2</span>
              }
              Tạo mã nạp tiền
            </button>
          </div>
        )}

        {/* ═══ STATE: QR CODE ═══ */}
        {(state === "qr" || state === "checking") && depositInfo && (
          <div className="glass-card p-6" style={{ boxShadow: "var(--shadow-card)" }}>
            {/* Timer */}
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-sm font-semibold flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
                <span className="material-symbols-rounded text-lg" style={{ color: "#10b981" }}>qr_code_2</span>
                Quét mã QR để thanh toán
              </h2>
              <div className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold"
                style={{
                  background: countdown < 60 ? "rgba(239,68,68,0.1)" : "rgba(16,185,129,0.1)",
                  color: countdown < 60 ? "#ef4444" : "#10b981",
                }}>
                <span className="material-symbols-rounded text-sm">timer</span>
                {formatTime(countdown)}
              </div>
            </div>

            {/* QR Image */}
            <div className="flex justify-center mb-5">
              <div className="rounded-xl overflow-hidden bg-white p-3" style={{ boxShadow: "0 4px 20px rgba(0,0,0,0.1)" }}>
                <img
                  src={depositInfo.qr_url}
                  alt="QR MBBank"
                  className="w-64 h-64 object-contain"
                />
              </div>
            </div>

            {/* Bank info */}
            <div className="space-y-3 mb-5">
              {[
                { label: "Ngân hàng", value: depositInfo.bank_name, icon: "account_balance" },
                { label: "Số tài khoản", value: depositInfo.bank_account, icon: "credit_card", copy: true },
                { label: "Số tiền", value: `${depositInfo.amount.toLocaleString()}đ`, icon: "payments" },
                { label: "Nội dung CK", value: depositInfo.transfer_content, icon: "description", copy: true },
              ].map((info) => (
                <div key={info.label} className="flex items-center justify-between rounded-lg px-4 py-3"
                  style={{ background: "var(--bg-tertiary)", border: "1px solid var(--border-subtle)" }}>
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-rounded text-base" style={{ color: "var(--text-muted)" }}>{info.icon}</span>
                    <span className="text-xs" style={{ color: "var(--text-muted)" }}>{info.label}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{info.value}</span>
                    {info.copy && (
                      <button
                        onClick={() => { navigator.clipboard.writeText(info.value); showToast("📋 Đã copy!", "success"); }}
                        className="p-1 rounded-md transition-colors"
                        style={{ color: "var(--neon-blue)" }}
                        onMouseEnter={(e) => e.currentTarget.style.background = "var(--bg-hover)"}
                        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                      >
                        <span className="material-symbols-rounded text-sm">content_copy</span>
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Action buttons */}
            {state === "qr" ? (
              <div className="flex gap-3">
                <button onClick={() => { setState("select"); setDepositInfo(null); }}
                  className="flex-1 btn-ghost py-3 text-sm font-medium">
                  ← Quay lại
                </button>
                <button onClick={handleStartCheck}
                  className="flex-1 py-3 rounded-xl text-white font-semibold text-sm flex items-center justify-center gap-2"
                  style={{ background: "linear-gradient(135deg, #10b981, #059669)", boxShadow: "0 4px 20px rgba(16,185,129,0.3)" }}>
                  <span className="material-symbols-rounded text-lg">check_circle</span>
                  Đã chuyển khoản
                </button>
              </div>
            ) : (
              <div className="text-center">
                <div className="flex items-center justify-center gap-3 mb-3">
                  <span className="spinner !w-5 !h-5" style={{ borderColor: "rgba(16,185,129,0.2)", borderTopColor: "#10b981" }}></span>
                  <span className="text-sm font-medium" style={{ color: "#10b981" }}>
                    Đang kiểm tra giao dịch... ({checkCount})
                  </span>
                </div>
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                  Hệ thống sẽ tự động cộng số dư khi nhận được chuyển khoản
                </p>
                <button onClick={() => { setState("select"); setDepositInfo(null); if (pollRef.current) clearInterval(pollRef.current); }}
                  className="mt-4 text-xs underline" style={{ color: "var(--text-muted)" }}>
                  Hủy
                </button>
              </div>
            )}
          </div>
        )}

        {/* ═══ STATE: SUCCESS ═══ */}
        {state === "success" && depositInfo && (
          <div className="glass-card p-8 text-center" style={{ boxShadow: "var(--shadow-card)" }}>
            <div className="inline-flex items-center justify-center w-20 h-20 rounded-full mb-5"
              style={{ background: "rgba(16,185,129,0.1)", border: "3px solid #10b981" }}>
              <span className="material-symbols-rounded text-4xl" style={{ color: "#10b981" }}>check_circle</span>
            </div>
            <h2 className="text-xl font-bold mb-2" style={{ color: "var(--text-primary)" }}>Nạp tiền thành công!</h2>
            <p className="text-3xl font-bold mb-1" style={{ color: "#10b981" }}>+{depositInfo.amount.toLocaleString()}đ</p>
            <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
              Số dư đã được cộng vào tài khoản
            </p>
            <div className="flex gap-3 justify-center">
              <button onClick={() => { setState("select"); setDepositInfo(null); }}
                className="btn-ghost px-6 py-2.5 text-sm font-medium">
                Nạp thêm
              </button>
              <button onClick={() => router.push("/")}
                className="px-6 py-2.5 rounded-xl text-white text-sm font-semibold"
                style={{ background: "var(--gradient-neon)" }}>
                Tạo video ngay
              </button>
            </div>
          </div>
        )}

        {/* Info section */}
        <div className="mt-6 rounded-xl p-5" style={{ background: "linear-gradient(135deg, rgba(99,102,241,0.06), rgba(168,85,247,0.06))", border: "1px solid rgba(99,102,241,0.15)" }}>
          <div className="flex items-start gap-3">
            <span className="material-symbols-rounded text-xl mt-0.5" style={{ color: "var(--neon-blue)" }}>info</span>
            <div>
              <p className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>Hướng dẫn nạp tiền</p>
              <ul className="text-xs space-y-1.5" style={{ color: "var(--text-secondary)" }}>
                <li className="flex items-start gap-1.5">
                  <span style={{ color: "#10b981" }}>①</span> Chọn số tiền muốn nạp và bấm "Tạo mã nạp tiền"
                </li>
                <li className="flex items-start gap-1.5">
                  <span style={{ color: "#10b981" }}>②</span> Quét mã QR bằng app ngân hàng hoặc chuyển khoản thủ công
                </li>
                <li className="flex items-start gap-1.5">
                  <span style={{ color: "#10b981" }}>③</span> Số dư sẽ được cộng tự động sau khi chuyển khoản
                </li>
                <li className="flex items-start gap-1.5">
                  <span style={{ color: "#10b981" }}>④</span> Dùng số dư để mua gói đăng ký và sử dụng dịch vụ
                </li>
                <li className="flex items-start gap-1.5">
                  <span style={{ color: "var(--text-muted)" }}>⚠️</span> Chuyển khoản đúng nội dung để hệ thống tự động nhận diện
                </li>
              </ul>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
