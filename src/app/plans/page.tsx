/**
 * Plans / Pricing Page — Gói đăng ký & Mua Credit
 * Premium card layout with feature highlights
 */
"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useStore } from "@/lib/store";
import { api } from "@/lib/api";
import { Navbar } from "@/components/Navbar";
import { Toast } from "@/components/Toast";

interface Plan {
  id: number;
  name: string;
  description: string;
  credits: number;
  price: number;
  duration_days: number;
  max_concurrent: number;
  features: string[];
}

export default function PlansPage() {
  const router = useRouter();
  const user = useStore((s) => s.user);
  const setUser = useStore((s) => s.setUser);
  const showToast = useStore((s) => s.showToast);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [loading, setLoading] = useState(true);

  // Auth check
  useEffect(() => {
    const stored = localStorage.getItem("veo3_user");
    const token = localStorage.getItem("veo3_token");
    if (stored && token) {
      try { setUser({ ...JSON.parse(stored), token }); } catch { router.push("/login"); }
    } else {
      router.push("/login");
    }
  }, [setUser, router]);

  // Fetch plans
  useEffect(() => {
    (async () => {
      try {
        const data = await api.getPlans();
        setPlans(data.plans || []);
      } catch { }
      setLoading(false);
    })();
  }, []);

  // Separate subscription plans vs credit pack
  const subscriptionPlans = plans.filter((p) => p.duration_days > 0);
  const creditPacks = plans.filter((p) => p.duration_days === 0 && p.price > 0);

  // Highlight the 3rd plan as "popular"
  const popularIdx = 2;

  const handleBuyPlan = (plan: Plan) => {
    if (!user) return;
    if ((user.balance ?? 0) < plan.price) {
      showToast("❌ Số dư không đủ. Vui lòng nạp tiền trước!", "error");
      setTimeout(() => router.push("/deposit"), 1500);
      return;
    }
    // TODO: implement actual plan purchase API
    showToast(`⏳ Chức năng mua gói "${plan.name}" sẽ sớm ra mắt!`, "info");
  };

  if (!user) return null;

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-primary)" }}>
      <Toast />
      <Navbar />

      <main style={{ paddingTop: 88, paddingBottom: 60 }} className="max-w-6xl mx-auto px-5">
        {/* Header */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl mb-4"
            style={{ background: "linear-gradient(135deg, var(--neon-blue), var(--neon-purple))", boxShadow: "0 8px 32px rgba(99,102,241,0.3)" }}>
            <span className="material-symbols-rounded text-3xl text-white">workspace_premium</span>
          </div>
          <h1 className="text-3xl font-bold mb-2" style={{ color: "var(--text-primary)" }}>
            Gói dịch vụ
          </h1>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            Chọn gói phù hợp với nhu cầu của bạn. Nâng cấp bất cứ lúc nào!
          </p>
        </div>

        {/* Current balance card */}
        <div className="max-w-lg mx-auto rounded-xl p-4 mb-8 flex items-center justify-between"
          style={{ background: "linear-gradient(135deg, rgba(99,102,241,0.08), rgba(168,85,247,0.08))", border: "1px solid rgba(99,102,241,0.15)" }}>
          <div className="flex items-center gap-3">
            <span className="material-symbols-rounded text-2xl" style={{ color: "var(--neon-blue)" }}>account_balance_wallet</span>
            <div>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>Số dư hiện tại</p>
              <p className="text-xl font-bold" style={{ color: "var(--neon-blue)" }}>{(user.balance ?? 0).toLocaleString()}đ</p>
            </div>
          </div>
          <button onClick={() => router.push("/deposit")}
            className="text-xs px-4 py-2 rounded-lg font-semibold transition-all"
            style={{ background: "linear-gradient(135deg, #10b981, #059669)", color: "white", boxShadow: "0 2px 12px rgba(16,185,129,0.3)" }}>
            + Nạp tiền
          </button>
        </div>

        {/* Loading */}
        {loading && (
          <div className="flex justify-center py-20">
            <div className="spinner spinner-lg"></div>
          </div>
        )}

        {/* ═══ Subscription Plans Grid ═══ */}
        {!loading && subscriptionPlans.length > 0 && (
          <>
            <h2 className="text-lg font-bold mb-5 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <span className="material-symbols-rounded" style={{ color: "var(--neon-purple)" }}>loyalty</span>
              Gói đăng ký
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4 mb-10">
              {subscriptionPlans.map((plan, idx) => {
                const isPopular = idx === popularIdx;
                const isFree = plan.price === 0;

                return (
                  <div
                    key={plan.id}
                    className="relative rounded-2xl p-5 flex flex-col transition-all hover:scale-[1.02]"
                    style={{
                      background: isPopular
                        ? "linear-gradient(160deg, rgba(99,102,241,0.12), rgba(168,85,247,0.08))"
                        : "var(--bg-card-solid)",
                      border: isPopular
                        ? "2px solid var(--neon-blue)"
                        : "1px solid var(--border-subtle)",
                      boxShadow: isPopular
                        ? "0 8px 40px rgba(99,102,241,0.2)"
                        : "var(--shadow-card)",
                    }}
                  >
                    {/* Popular badge */}
                    {isPopular && (
                      <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 rounded-full text-[10px] font-bold text-white"
                        style={{ background: "linear-gradient(135deg, var(--neon-blue), var(--neon-purple))" }}>
                        ⭐ PHỔ BIẾN
                      </div>
                    )}

                    {/* Plan name */}
                    <h3 className="text-base font-bold mb-1" style={{ color: "var(--text-primary)" }}>
                      {plan.name}
                    </h3>
                    <p className="text-[11px] mb-4" style={{ color: "var(--text-muted)" }}>
                      {plan.description}
                    </p>

                    {/* Price */}
                    <div className="mb-4">
                      <span className="text-2xl font-extrabold" style={{ color: isFree ? "#10b981" : "var(--text-primary)" }}>
                        {isFree ? "Miễn phí" : `${plan.price.toLocaleString()}đ`}
                      </span>
                      {!isFree && (
                        <span className="text-xs ml-1" style={{ color: "var(--text-muted)" }}>
                          /{plan.duration_days} ngày
                        </span>
                      )}
                    </div>

                    {/* Credits */}
                    <div className="flex items-center gap-2 mb-4 px-3 py-2 rounded-lg"
                      style={{ background: "rgba(99,102,241,0.08)" }}>
                      <span className="material-symbols-rounded text-sm" style={{ color: "var(--neon-blue)" }}>bolt</span>
                      <span className="text-sm font-bold" style={{ color: "var(--neon-blue)" }}>
                        {plan.credits.toLocaleString()} credits
                      </span>
                    </div>

                    {/* Features */}
                    <ul className="flex-1 space-y-2 mb-5">
                      {plan.features.map((f, i) => (
                        <li key={i} className="flex items-start gap-2 text-xs" style={{ color: "var(--text-secondary)" }}>
                          <span className="material-symbols-rounded text-sm mt-px" style={{ color: "#10b981" }}>check_circle</span>
                          {f}
                        </li>
                      ))}
                    </ul>

                    {/* CTA Button */}
                    <button
                      onClick={() => handleBuyPlan(plan)}
                      className="w-full py-2.5 rounded-xl text-sm font-semibold transition-all"
                      style={{
                        background: isPopular
                          ? "linear-gradient(135deg, var(--neon-blue), var(--neon-purple))"
                          : isFree
                            ? "linear-gradient(135deg, #10b981, #059669)"
                            : "var(--bg-tertiary)",
                        color: isPopular || isFree ? "white" : "var(--text-primary)",
                        border: !isPopular && !isFree ? "1px solid var(--border-subtle)" : "none",
                        boxShadow: isPopular ? "0 4px 20px rgba(99,102,241,0.3)" : "none",
                      }}
                    >
                      {isFree ? "Bắt đầu miễn phí" : "Mua gói"}
                    </button>
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* ═══ Credit Purchase Section ═══ */}
        {!loading && creditPacks.length > 0 && (
          <>
            <h2 className="text-lg font-bold mb-5 flex items-center gap-2" style={{ color: "var(--text-primary)" }}>
              <span className="material-symbols-rounded" style={{ color: "#f59e0b" }}>shopping_cart</span>
              Mua thêm Credit
            </h2>

            <div className="max-w-lg">
              {creditPacks.map((pack) => (
                <div key={pack.id}
                  className="rounded-2xl p-5 flex items-center justify-between transition-all hover:scale-[1.01]"
                  style={{
                    background: "linear-gradient(135deg, rgba(245,158,11,0.08), rgba(249,115,22,0.05))",
                    border: "1px solid rgba(245,158,11,0.2)",
                    boxShadow: "0 4px 20px rgba(245,158,11,0.1)",
                  }}>
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-xl flex items-center justify-center"
                      style={{ background: "linear-gradient(135deg, #f59e0b, #f97316)" }}>
                      <span className="material-symbols-rounded text-2xl text-white">bolt</span>
                    </div>
                    <div>
                      <h3 className="text-base font-bold" style={{ color: "var(--text-primary)" }}>{pack.name}</h3>
                      <p className="text-xs" style={{ color: "var(--text-muted)" }}>{pack.description}</p>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-lg font-extrabold" style={{ color: "#f59e0b" }}>
                          {pack.price.toLocaleString()}đ
                        </span>
                        <span className="text-xs px-2 py-0.5 rounded-full font-bold"
                          style={{ background: "rgba(245,158,11,0.15)", color: "#f59e0b" }}>
                          = {pack.credits.toLocaleString()} credits
                        </span>
                      </div>
                    </div>
                  </div>

                  <button
                    onClick={() => handleBuyPlan(pack)}
                    className="px-5 py-2.5 rounded-xl text-sm font-semibold text-white transition-all"
                    style={{ background: "linear-gradient(135deg, #f59e0b, #f97316)", boxShadow: "0 4px 16px rgba(245,158,11,0.3)" }}>
                    Mua ngay
                  </button>
                </div>
              ))}
            </div>
          </>
        )}

        {/* Info */}
        <div className="mt-8 rounded-xl p-5 max-w-lg" style={{ background: "rgba(99,102,241,0.04)", border: "1px solid rgba(99,102,241,0.1)" }}>
          <div className="flex items-start gap-3">
            <span className="material-symbols-rounded text-xl mt-0.5" style={{ color: "var(--neon-blue)" }}>info</span>
            <div>
              <p className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>Lưu ý</p>
              <ul className="text-xs space-y-1.5" style={{ color: "var(--text-secondary)" }}>
                <li>• 1 credit = 1 lượt tạo video hoặc ảnh</li>
                <li>• Credits sẽ được cộng ngay sau khi mua gói</li>
                <li>• Gói đăng ký sẽ tự động hết hạn theo thời gian</li>
                <li>• Credits mua thêm không có thời hạn</li>
                <li>• Liên hệ admin nếu cần hỗ trợ</li>
              </ul>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
