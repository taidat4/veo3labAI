/**
 * Plans Page — 2 tabs: Gói dịch vụ + Nạp tiền
 */
"use client";
import { useEffect, useState, useRef } from "react";
import { useRouter } from "next/navigation";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import { Navbar } from "@/components/Navbar";
import { Toast } from "@/components/Toast";

interface Plan {
  id: number; name: string; description: string; credits: number;
  price: number; duration_days: number; max_concurrent: number; features: string[];
}
interface DepositInfo {
  token: string; amount: number; credits: number; qr_url: string;
  bank_name: string; bank_account: string; transfer_content: string; expires_at: string;
}

const PRESET_AMOUNTS = [
  { amount: 50000, label: "50K" }, { amount: 100000, label: "100K" },
  { amount: 200000, label: "200K" }, { amount: 500000, label: "500K" },
  { amount: 1000000, label: "1M" }, { amount: 2000000, label: "2M" },
];

export default function PlansPage() {
  const router = useRouter();
  const user = useStore((s) => s.user);
  const setUser = useStore((s) => s.setUser);
  const showToast = useStore((s) => s.showToast);

  // Tab state — read from URL ?tab=deposit
  const [activeTab, setActiveTab] = useState<"plans" | "deposit">("plans");

  // Plans state
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loadingPlans, setLoadingPlans] = useState(true);

  // Deposit state
  const [depositState, setDepositState] = useState<"select" | "qr" | "checking" | "success">("select");
  const [selectedAmount, setSelectedAmount] = useState(100000);
  const [customAmount, setCustomAmount] = useState("");
  const [depositLoading, setDepositLoading] = useState(false);
  const [depositInfo, setDepositInfo] = useState<DepositInfo | null>(null);
  const [countdown, setCountdown] = useState(0);
  const [checkCount, setCheckCount] = useState(0);
  const pollRef = useRef<NodeJS.Timeout | null>(null);

  // Buy credits state
  const [showBuyCredits, setShowBuyCredits] = useState(false);
  const [buyAmount, setBuyAmount] = useState("");
  const [creditRate, setCreditRate] = useState(100); // credits per 1000đ
  const [buyingCredits, setBuyingCredits] = useState(false);
  const [buyingPlanId, setBuyingPlanId] = useState<number | null>(null);

  // Auth
  useEffect(() => {
    const stored = localStorage.getItem("veo3_user");
    const token = localStorage.getItem("veo3_token");
    if (stored && token) {
      try { setUser({ ...JSON.parse(stored), token }); } catch { router.push("/login"); }
    } else { router.push("/login"); }
    // Read tab from URL
    if (typeof window !== "undefined" && window.location.search.includes("tab=deposit")) {
      setActiveTab("deposit");
    }
  }, [setUser, router]);

  // Fetch plans
  useEffect(() => {
    (async () => {
      try { const d = await api.getPlans(); setPlans(d.plans || []); } catch { }
      setLoadingPlans(false);
    })();
  }, []);

  // Fetch credit rate
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/credit-rate");
        if (res.ok) {
          const d = await res.json();
          setCreditRate(d.rate || 100);
        }
      } catch { }
    })();
  }, []);
  // Deposit countdown
  useEffect(() => {
    if (depositState !== "qr" && depositState !== "checking") return;
    if (!depositInfo?.expires_at) return;
    const iv = setInterval(() => {
      const rem = Math.max(0, Math.floor((new Date(depositInfo.expires_at).getTime() - Date.now()) / 1000));
      setCountdown(rem);
      if (rem <= 0) { setDepositState("select"); setDepositInfo(null); showToast("⏰ Mã nạp tiền đã hết hạn!", "error"); clearInterval(iv); }
    }, 1000);
    return () => clearInterval(iv);
  }, [depositState, depositInfo, showToast]);

  // Deposit auto-poll — start polling immediately when QR is shown
  useEffect(() => {
    if ((depositState !== "qr" && depositState !== "checking") || !depositInfo?.token) return;
    setCheckCount(0);
    pollRef.current = setInterval(async () => {
      setCheckCount(p => { if (p >= 200) { if (pollRef.current) clearInterval(pollRef.current); showToast("⏰ Timeout", "error"); setDepositState("select"); setDepositInfo(null); return 0; } return p + 1; });
      try {
        const token = localStorage.getItem("veo3_token");
        const res = await fetch(`/api/deposit/verify/${depositInfo.token}`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
        const data = await res.json();
        if (data.status === "completed") {
          setDepositState("success");
          showToast(`🎉 Nạp thành công! +${data.amount?.toLocaleString()}đ`, "success");
          if (data.new_balance != null) {
            const s = localStorage.getItem("veo3_user");
            if (s) { const u = JSON.parse(s); u.balance = data.new_balance; localStorage.setItem("veo3_user", JSON.stringify(u)); setUser({ ...u, token }); }
          }
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch { }
    }, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [depositState, depositInfo, showToast, setUser]);

  const handleCreateDeposit = async () => {
    const amount = customAmount ? parseInt(customAmount) : selectedAmount;
    if (amount < 2000) { showToast("Số tiền tối thiểu 2,000đ", "error"); return; }
    setDepositLoading(true);
    try {
      const token = localStorage.getItem("veo3_token");
      const res = await fetch("/api/deposit/request", { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ amount }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Lỗi");
      setDepositInfo(data); setDepositState("qr");
    } catch (e: any) { showToast(e.message, "error"); }
    finally { setDepositLoading(false); }
  };



  const handleBuyPlan = async (plan: Plan) => {
    if (!user) return;
    if (plan.price > 0 && (user.balance ?? 0) < plan.price) {
      showToast("❌ Số dư không đủ! Chuyển sang tab Nạp tiền.", "error");
      setActiveTab("deposit");
      return;
    }
    setBuyingPlanId(plan.id);
    try {
      const res = await api.purchasePlan(plan.id);
      if (res.success) {
        showToast(`🎉 ${res.message}`, "success");
        // Update user balance + credits
        const stored = localStorage.getItem("veo3_user");
        const token = localStorage.getItem("veo3_token");
        if (stored && token) {
          const u = JSON.parse(stored);
          u.balance = res.new_balance;
          u.credits = res.new_credits;
          localStorage.setItem("veo3_user", JSON.stringify(u));
          setUser({ ...u, token });
        }
      }
    } catch (e: any) {
      showToast(e.message || "Lỗi mua gói", "error");
    } finally {
      setBuyingPlanId(null);
    }
  };

  const subscriptionPlans = plans.filter((p) => p.duration_days > 0).sort((a, b) => a.price - b.price);
  const creditPacks = plans.filter((p) => p.duration_days === 0 && p.price > 0);
  const activeAmount = customAmount ? parseInt(customAmount) || 0 : selectedAmount;
  const formatTime = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;

  if (!user) return null;

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Toast />
      <Navbar />
      <main style={{ paddingTop: 88, paddingBottom: 60 }} className="max-w-6xl mx-auto px-5">
        {/* Header */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl mb-3"
            style={{ background: "linear-gradient(135deg, var(--neon-blue), var(--neon-purple))", boxShadow: "0 8px 32px rgba(99,102,241,0.3)" }}>
            <span className="material-symbols-rounded text-2xl text-white">workspace_premium</span>
          </div>
          <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text-primary)" }}>Gói Đăng Ký</h1>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>Chọn gói phù hợp hoặc nạp tiền vào tài khoản</p>
        </div>

        {/* Balance bar */}
        <div className="max-w-lg mx-auto rounded-xl p-3 mb-6 flex items-center justify-between"
          style={{ background: "linear-gradient(135deg, rgba(99,102,241,0.08), rgba(168,85,247,0.08))", border: "1px solid rgba(99,102,241,0.15)" }}>
          <div className="flex items-center gap-2">
            <span className="material-symbols-rounded text-xl" style={{ color: "#a855f7" }}>bolt</span>
            <div>
              <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>Credits</p>
              <p className="text-lg font-bold" style={{ color: "#a855f7" }}>{(user.credits ?? 0).toLocaleString()}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="material-symbols-rounded text-xl" style={{ color: "var(--neon-blue)" }}>account_balance_wallet</span>
            <div>
              <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>Số dư</p>
              <p className="text-lg font-bold" style={{ color: "var(--neon-blue)" }}>{(user.balance ?? 0).toLocaleString()}đ</p>
            </div>
          </div>
        </div>

        {/* ═══ TABS ═══ */}
        <div className="flex items-center justify-center gap-1 mb-8 p-1 rounded-xl max-w-sm mx-auto"
          style={{ background: "var(--bg-tertiary)" }}>
          {([
            { key: "plans" as const, label: "Gói dịch vụ", icon: "loyalty" },
            { key: "deposit" as const, label: "Nạp tiền", icon: "account_balance_wallet" },
          ]).map(t => (
            <button key={t.key} onClick={() => setActiveTab(t.key)}
              className="flex-1 flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all"
              style={{
                background: activeTab === t.key ? "var(--neon-blue)" : "transparent",
                color: activeTab === t.key ? "white" : "var(--text-muted)",
              }}>
              <span className="material-symbols-rounded text-base">{t.icon}</span>
              {t.label}
            </button>
          ))}
        </div>

        {/* ════════════════ TAB: GÓI DỊCH VỤ ════════════════ */}
        {activeTab === "plans" && (
          <>
            {loadingPlans && <div className="flex justify-center py-16"><div className="spinner spinner-lg" /></div>}

            {!loadingPlans && subscriptionPlans.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4 mb-8" style={{ alignItems: "stretch" }}>
                {subscriptionPlans.map((plan, idx) => {
                  const isFree = plan.price === 0;
                  const paidPlans = subscriptionPlans.filter(p => p.price > 0);
                  const middleIdx = Math.floor(paidPlans.length / 2);
                  const isPopular = !isFree && paidPlans[middleIdx]?.id === plan.id;
                  return (
                    <div key={plan.id} className="relative rounded-2xl p-5 flex flex-col transition-all hover:scale-[1.02]"
                      style={{
                        background: isPopular ? "linear-gradient(160deg, rgba(99,102,241,0.12), rgba(168,85,247,0.08))" : "var(--bg-card-solid)",
                        border: isPopular ? "2px solid var(--neon-blue)" : "1px solid var(--border-subtle)",
                        boxShadow: isPopular ? "0 8px 40px rgba(99,102,241,0.2)" : "var(--shadow-card)",
                        minHeight: 320,
                      }}>
                      {isPopular && (
                        <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full text-[10px] font-bold text-white"
                          style={{ background: "linear-gradient(135deg, var(--neon-blue), var(--neon-purple))" }}>⭐ PHỔ BIẾN</div>
                      )}
                      <h3 className="text-base font-bold mb-1" style={{ color: "var(--text-primary)" }}>{plan.name}</h3>
                      <p className="text-[11px] mb-3" style={{ color: "var(--text-muted)", minHeight: 30 }}>{plan.description}</p>
                      <div className="mb-3">
                        <span className="text-2xl font-extrabold" style={{ color: isFree ? "#10b981" : "var(--text-primary)" }}>
                          {isFree ? "Miễn phí" : `${plan.price.toLocaleString()}đ`}
                        </span>
                        {!isFree && <span className="text-xs ml-1" style={{ color: "var(--text-muted)" }}>/{plan.duration_days} ngày</span>}
                      </div>
                      <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg" style={{ background: "rgba(99,102,241,0.08)" }}>
                        <span className="material-symbols-rounded text-sm" style={{ color: "var(--neon-blue)" }}>bolt</span>
                        <span className="text-sm font-bold" style={{ color: "var(--neon-blue)" }}>{plan.credits.toLocaleString()} credits</span>
                      </div>
                      <ul className="flex-1 space-y-1.5 mb-4">
                        {(Array.isArray(plan.features) ? plan.features : []).map((f: string, i: number) => (
                          <li key={i} className="flex items-start gap-1.5 text-[11px]" style={{ color: "var(--text-secondary)" }}>
                            <span className="material-symbols-rounded text-xs mt-px" style={{ color: "#10b981" }}>check_circle</span>{f}
                          </li>
                        ))}
                      </ul>
                      <button onClick={() => handleBuyPlan(plan)} className="w-full py-2.5 rounded-xl text-sm font-semibold transition-all mt-auto"
                        style={{
                          background: isPopular ? "linear-gradient(135deg, var(--neon-blue), var(--neon-purple))" : isFree ? "linear-gradient(135deg, #10b981, #059669)" : "var(--bg-tertiary)",
                          color: isPopular || isFree ? "white" : "var(--text-primary)",
                          border: !isPopular && !isFree ? "1px solid var(--border-subtle)" : "none",
                        }}>
                        {isFree ? "Bắt đầu miễn phí" : "Mua gói"}
                      </button>
                    </div>
                  );
                })}
              </div>
            )}


            {/* Buy Credits Button */}
            {!loadingPlans && (
              <div className="max-w-lg mx-auto">
                <button onClick={() => setShowBuyCredits(true)}
                  className="w-full rounded-2xl p-4 flex items-center justify-between transition-all hover:scale-[1.01]"
                  style={{ background: "linear-gradient(135deg, rgba(245,158,11,0.08), rgba(249,115,22,0.05))", border: "1px solid rgba(245,158,11,0.2)" }}>
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: "linear-gradient(135deg, #f59e0b, #f97316)" }}>
                      <span className="material-symbols-rounded text-xl text-white">bolt</span>
                    </div>
                    <div className="text-left">
                      <h3 className="text-sm font-bold" style={{ color: "var(--text-primary)" }}>Mua thêm Credit</h3>
                      <p className="text-xs" style={{ color: "var(--text-muted)" }}>Dùng số dư VND để mua credits ({creditRate} credits / 1.000đ)</p>
                    </div>
                  </div>
                  <span className="material-symbols-rounded text-xl" style={{ color: "#f59e0b" }}>arrow_forward</span>
                </button>
              </div>
            )}
          </>
        )}

        {/* ════════════════ TAB: NẠP TIỀN ════════════════ */}
        {activeTab === "deposit" && (
          <div className="max-w-xl mx-auto">
            {/* Select amount */}
            {depositState === "select" && (
              <div className="glass-card p-6" style={{ boxShadow: "var(--shadow-card)" }}>
                <h2 className="text-sm font-semibold mb-4 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
                  <span className="material-symbols-rounded text-lg" style={{ color: "#10b981" }}>payments</span>Chọn số tiền nạp
                </h2>
                <div className="grid grid-cols-3 gap-3 mb-5">
                  {PRESET_AMOUNTS.map(p => (
                    <button key={p.amount} onClick={() => { setSelectedAmount(p.amount); setCustomAmount(""); }}
                      className="rounded-xl p-3 text-center transition-all"
                      style={{
                        background: selectedAmount === p.amount && !customAmount ? "linear-gradient(135deg, #10b981, #059669)" : "var(--bg-tertiary)",
                        color: selectedAmount === p.amount && !customAmount ? "white" : "var(--text-primary)",
                        border: `2px solid ${selectedAmount === p.amount && !customAmount ? "#10b981" : "var(--border-subtle)"}`,
                      }}>
                      <p className="text-lg font-bold">{p.label}</p>
                      <p className="text-xs opacity-75">{p.amount.toLocaleString()}đ</p>
                    </button>
                  ))}
                </div>
                <div className="mb-5">
                  <label className="text-xs font-semibold block mb-2" style={{ color: "var(--text-muted)" }}>Hoặc nhập tùy chỉnh</label>
                  <div className="flex items-center gap-3">
                    <input type="number" value={customAmount} onChange={e => setCustomAmount(e.target.value)}
                      placeholder="Nhập số tiền..." className="input-field flex-1" min={2000} step={1000} />
                    <span className="text-sm font-medium" style={{ color: "var(--text-muted)" }}>VNĐ</span>
                  </div>
                </div>
                <div className="rounded-xl p-4 mb-5 flex items-center justify-between" style={{ background: "var(--bg-tertiary)" }}>
                  <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>Số tiền nạp</span>
                  <span className="text-lg font-bold" style={{ color: "#10b981" }}>+{activeAmount.toLocaleString()}đ</span>
                </div>
                <button onClick={handleCreateDeposit} disabled={depositLoading || activeAmount < 2000}
                  className="w-full py-3.5 rounded-xl text-white font-semibold text-sm flex items-center justify-center gap-2"
                  style={{ background: activeAmount >= 2000 ? "linear-gradient(135deg, #10b981, #059669)" : "var(--bg-tertiary)", color: activeAmount >= 2000 ? "white" : "var(--text-muted)" }}>
                  {depositLoading ? <span className="spinner !w-5 !h-5 !border-white/20 !border-t-white" /> : <span className="material-symbols-rounded text-lg">qr_code_2</span>}
                  Tạo mã nạp tiền
                </button>
              </div>
            )}

            {/* QR / Checking */}
            {(depositState === "qr" || depositState === "checking") && depositInfo && (
              <div className="glass-card p-6" style={{ boxShadow: "var(--shadow-card)" }}>
                <div className="flex items-center justify-between mb-5">
                  <h2 className="text-sm font-semibold flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
                    <span className="material-symbols-rounded text-lg" style={{ color: "#10b981" }}>qr_code_2</span>Quét mã QR
                  </h2>
                  <div className="px-3 py-1 rounded-full text-xs font-bold"
                    style={{ background: countdown < 60 ? "rgba(239,68,68,0.1)" : "rgba(16,185,129,0.1)", color: countdown < 60 ? "#ef4444" : "#10b981" }}>
                    {formatTime(countdown)}
                  </div>
                </div>
                <div className="flex justify-center mb-5">
                  <div className="rounded-xl overflow-hidden bg-white p-3" style={{ boxShadow: "0 4px 20px rgba(0,0,0,0.1)" }}>
                    <img src={depositInfo.qr_url} alt="QR" className="w-56 h-56 object-contain" />
                  </div>
                </div>
                <div className="space-y-2 mb-5">
                  {[
                    { label: "Ngân hàng", value: depositInfo.bank_name, icon: "account_balance" },
                    { label: "STK", value: depositInfo.bank_account, icon: "credit_card", copy: true },
                    { label: "Số tiền", value: `${depositInfo.amount.toLocaleString()}đ`, icon: "payments" },
                    { label: "Nội dung", value: depositInfo.transfer_content, icon: "description", copy: true },
                  ].map(info => (
                    <div key={info.label} className="flex items-center justify-between rounded-lg px-4 py-2.5" style={{ background: "var(--bg-tertiary)" }}>
                      <div className="flex items-center gap-2">
                        <span className="material-symbols-rounded text-sm" style={{ color: "var(--text-muted)" }}>{info.icon}</span>
                        <span className="text-xs" style={{ color: "var(--text-muted)" }}>{info.label}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{info.value}</span>
                        {info.copy && (
                          <button onClick={() => { navigator.clipboard.writeText(info.value); showToast("📋 Đã copy!", "success"); }}
                            className="p-1 rounded-md" style={{ color: "var(--neon-blue)" }}>
                            <span className="material-symbols-rounded text-sm">content_copy</span>
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="text-center">
                    <div className="flex items-center justify-center gap-3 mb-2">
                      <span className="spinner !w-5 !h-5" style={{ borderColor: "rgba(16,185,129,0.2)", borderTopColor: "#10b981" }} />
                      <span className="text-sm font-medium" style={{ color: "#10b981" }}>Đang kiểm tra... ({checkCount})</span>
                    </div>
                    <button onClick={() => { setDepositState("select"); setDepositInfo(null); if (pollRef.current) clearInterval(pollRef.current); }}
                      className="mt-1 text-xs underline" style={{ color: "var(--text-muted)" }}>Hủy</button>
                  </div>
              </div>
            )}

            {/* Success */}
            {depositState === "success" && depositInfo && (
              <div className="glass-card p-8 text-center" style={{ boxShadow: "var(--shadow-card)" }}>
                <div className="inline-flex items-center justify-center w-16 h-16 rounded-full mb-4"
                  style={{ background: "rgba(16,185,129,0.1)", border: "3px solid #10b981" }}>
                  <span className="material-symbols-rounded text-3xl" style={{ color: "#10b981" }}>check_circle</span>
                </div>
                <h2 className="text-xl font-bold mb-2" style={{ color: "var(--text-primary)" }}>Nạp thành công!</h2>
                <p className="text-2xl font-bold mb-4" style={{ color: "#10b981" }}>+{depositInfo.amount.toLocaleString()}đ</p>
                <div className="flex gap-3 justify-center">
                  <button onClick={() => { setDepositState("select"); setDepositInfo(null); }} className="btn-ghost px-5 py-2 text-sm">Nạp thêm</button>
                  <button onClick={() => setActiveTab("plans")} className="px-5 py-2 rounded-xl text-white text-sm font-semibold"
                    style={{ background: "var(--gradient-neon)" }}>Mua gói ngay</button>
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {/* ════════════════ MODAL: MUA CREDIT ════════════════ */}
      {showBuyCredits && (
        <div className="fixed inset-0 z-50 flex items-center justify-center px-4"
          style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(6px)" }}
          onClick={(e) => { if (e.target === e.currentTarget) setShowBuyCredits(false); }}>
          <div className="w-full max-w-md rounded-2xl p-6" style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}>
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-lg font-bold flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
                <span className="material-symbols-rounded" style={{ color: "#f59e0b" }}>bolt</span>
                Mua Credit
              </h2>
              <button onClick={() => setShowBuyCredits(false)} className="btn-ghost !p-1.5">
                <span className="material-symbols-rounded text-lg">close</span>
              </button>
            </div>

            <p className="text-xs mb-4" style={{ color: "var(--text-muted)" }}>
              Tỷ giá: <strong style={{ color: "#f59e0b" }}>{creditRate} credits</strong> / 1.000đ — Tối thiểu 1.000đ
            </p>

            {/* Quick amounts */}
            <div className="grid grid-cols-4 gap-2 mb-4">
              {[5000, 10000, 50000, 100000].map(amt => (
                <button key={amt} onClick={() => setBuyAmount(String(amt))}
                  className="py-2 rounded-lg text-xs font-medium transition-all"
                  style={{
                    background: buyAmount === String(amt) ? "rgba(245,158,11,0.15)" : "var(--bg-tertiary)",
                    color: buyAmount === String(amt) ? "#f59e0b" : "var(--text-secondary)",
                    border: buyAmount === String(amt) ? "1px solid rgba(245,158,11,0.4)" : "1px solid var(--border-subtle)",
                  }}>
                  {(amt / 1000).toLocaleString()}K
                </button>
              ))}
            </div>

            {/* Custom input */}
            <div className="mb-4">
              <label className="text-xs font-medium mb-1.5 block" style={{ color: "var(--text-muted)" }}>Số tiền (VNĐ)</label>
              <input type="number" value={buyAmount} onChange={e => setBuyAmount(e.target.value)}
                placeholder="Nhập số tiền..." min="1000" step="1000"
                className="input-field !text-lg !font-bold" />
            </div>

            {/* Preview */}
            {parseInt(buyAmount) >= 1000 && (
              <div className="rounded-xl p-4 mb-4 flex items-center justify-between"
                style={{ background: "linear-gradient(135deg, rgba(245,158,11,0.08), rgba(249,115,22,0.05))", border: "1px solid rgba(245,158,11,0.15)" }}>
                <div>
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>Bạn sẽ nhận được</p>
                  <p className="text-2xl font-extrabold" style={{ color: "#f59e0b" }}>
                    {Math.floor(parseInt(buyAmount) / 1000 * creditRate).toLocaleString()} credits
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>Trừ từ số dư</p>
                  <p className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
                    {parseInt(buyAmount).toLocaleString()}đ
                  </p>
                </div>
              </div>
            )}

            <button disabled={buyingCredits || !buyAmount || parseInt(buyAmount) < 1000}
              onClick={async () => {
                if (!user) return;
                setBuyingCredits(true);
                try {
                  const token = localStorage.getItem("veo3_token");
                  const res = await fetch("/api/buy-credits", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
                    body: JSON.stringify({ amount: parseInt(buyAmount) }),
                  });
                  const data = await res.json();
                  if (!res.ok) throw new Error(data.detail || "Lỗi mua credit");
                  showToast(`🎉 ${data.message}`, "success");
                  const stored = localStorage.getItem("veo3_user");
                  if (stored && token) {
                    const u = JSON.parse(stored);
                    u.balance = data.new_balance;
                    u.credits = data.new_credits;
                    localStorage.setItem("veo3_user", JSON.stringify(u));
                    setUser({ ...u, token });
                  }
                  setShowBuyCredits(false);
                  setBuyAmount("");
                } catch (e: any) {
                  showToast(e.message || "Lỗi", "error");
                } finally {
                  setBuyingCredits(false);
                }
              }}
              className="w-full py-3 rounded-xl text-sm font-bold text-white transition-all flex items-center justify-center gap-2"
              style={{
                background: buyingCredits || !buyAmount || parseInt(buyAmount) < 1000
                  ? "var(--bg-tertiary)" : "linear-gradient(135deg, #f59e0b, #f97316)",
                opacity: buyingCredits || !buyAmount || parseInt(buyAmount) < 1000 ? 0.5 : 1,
              }}>
              {buyingCredits ? <span className="spinner !w-4 !h-4 !border-white/20 !border-t-white" /> : (
                <span className="material-symbols-rounded text-lg">shopping_cart</span>
              )}
              {buyingCredits ? "Đang xử lý..." : "Mua Credit"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
