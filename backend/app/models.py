"""
Database Models — SQLAlchemy 2.0 ORM
Tất cả bảng cho hệ thống Veo3 resell
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Float,
    ForeignKey, JSON, Index,
)
from sqlalchemy.orm import relationship
from app.database import Base
import enum


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class AccountStatus(str, enum.Enum):
    """Trạng thái tài khoản Ultra"""
    HEALTHY = "healthy"      # Đang hoạt động tốt
    REFRESHING = "refreshing"  # Đang refresh session
    EXPIRED = "expired"      # Session hết hạn, cần refresh
    BANNED = "banned"        # Bị Google ban
    DISABLED = "disabled"    # Admin tắt thủ công


class JobStatus(str, enum.Enum):
    """Trạng thái job tạo video"""
    WAITING = "waiting"        # Chờ slot (queue overflow, max 8 concurrent)
    QUEUED = "queued"          # Đang chờ trong queue
    PENDING = "pending"        # Worker đã nhận, đang chuẩn bị
    PROCESSING = "processing"  # Đang tạo video (Google đang render)
    COMPLETED = "completed"    # Hoàn thành, có video URL
    FAILED = "failed"          # Thất bại
    CANCELLED = "cancelled"    # User hủy


# ═══════════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class User(Base):
    """Người dùng cuối (khách hàng mua video)"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=True)
    balance = Column(Integer, default=0)       # Số dư (VNĐ)
    total_deposit = Column(Integer, default=0)  # Tổng nạp
    role = Column(String(20), default="customer")  # customer | admin
    is_banned = Column(Boolean, default=False)
    api_key = Column(String(64), unique=True, nullable=True, index=True)  # API key cho external app
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=True)  # Gói đăng ký
    plan_expires_at = Column(DateTime, nullable=True)  # Hết hạn gói
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    jobs = relationship("GenerationJob", back_populates="user")
    rate_limit = relationship("UserRateLimit", back_populates="user", uselist=False)

    def __repr__(self):
        return f"<User {self.username}>"


class UltraAccount(Base):
    """Tài khoản Google Ultra dùng để tạo video"""
    __tablename__ = "ultra_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password = Column(String(255), nullable=False)
    totp_secret = Column(String(100), nullable=True)  # 2FA secret nếu có
    proxy_url = Column(String(500), nullable=True)     # Residential proxy VN
    flow_project_url = Column(String(500), nullable=True)  # Link project Flow cố định (lấy token nhanh)
    cookies = Column(Text, nullable=True)  # Browser cookies string for NanoAI upscale API

    # ── Bearer Token (Flow API) ──
    bearer_token = Column(Text, nullable=True)         # ya29.xxx token
    token_expires_at = Column(DateTime, nullable=True)  # Khi nào hết hạn
    token_source = Column(String(20), default="manual")  # manual | auto-refresh

    # ── Trạng thái ──
    status = Column(
        String(20),
        default="healthy",
    )
    is_enabled = Column(Boolean, default=True, server_default="1")  # Manual ON/OFF toggle
    health_score = Column(Integer, default=100)         # 0-100, cao = tốt
    fail_count = Column(Integer, default=0)             # Lỗi liên tiếp
    usage_count = Column(Integer, default=0)            # Tổng số video đã tạo
    current_concurrent = Column(Integer, default=0)     # Số job đang chạy
    max_concurrent = Column(Integer, default=40)        # Giới hạn concurrent

    # ── Timestamps ──
    last_refresh_at = Column(DateTime, nullable=True)
    last_health_check = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    sessions = relationship("SessionData", back_populates="account", cascade="all, delete-orphan")
    jobs = relationship("GenerationJob", back_populates="account")

    def __repr__(self):
        return f"<UltraAccount {self.email} [{self.status}]>"


class SessionData(Base):
    """Dữ liệu session đầy đủ cho 1 lần login"""
    __tablename__ = "session_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey("ultra_accounts.id", ondelete="CASCADE"), nullable=False)

    # ── Cookies quan trọng ──
    cookies = Column(JSON, nullable=True)  # Dict tất cả cookies
    secure_1psid = Column(Text, nullable=True)   # __Secure-1PSID
    secure_1psidts = Column(Text, nullable=True)  # __Secure-1PSIDTS

    # ── Gemini web tokens ──
    snl_m0e = Column(Text, nullable=True)   # WIZ_global_data.SNlM0e
    f_sid = Column(Text, nullable=True)      # f.sid
    bl = Column(Text, nullable=True)         # bl parameter

    # ── Headers phụ ──
    headers_extra = Column(JSON, nullable=True)  # x-goog-ext-* headers

    # ── Thời gian ──
    expire_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relations
    account = relationship("UltraAccount", back_populates="sessions")

    def __repr__(self):
        return f"<SessionData acc={self.account_id} expires={self.expire_at}>"


class GenerationJob(Base):
    """Một job tạo video Veo"""
    __tablename__ = "generation_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("ultra_accounts.id"), nullable=True)

    # ── Nội dung ──
    prompt = Column(Text, nullable=False)
    params = Column(JSON, default=dict)  # aspect_ratio, duration, style, resolution
    model_key = Column(String(100), default="veo_3_1_fov_fast_ultra_relaxed")
    batch_id = Column(String(100), nullable=True)  # Nhóm nhiều video cùng 1 request

    # ── Trạng thái ──
    status = Column(
        String(20),
        default="queued",
        index=True,
    )
    progress_percent = Column(Integer, default=0)  # 0-100
    operation_id = Column(String(500), nullable=True)  # Google operation ID
    celery_task_id = Column(String(100), nullable=True)

    # ── Video output ──
    temp_video_url = Column(Text, nullable=True)   # URL tạm từ Google
    r2_key = Column(String(500), nullable=True)     # Key trong R2
    r2_url = Column(Text, nullable=True)            # Public URL từ R2
    media_id = Column(String(200), nullable=True)   # Google media ID (cho upscale)

    # ── Cost ──
    cost = Column(Integer, default=0)  # Chi phí VNĐ
    error = Column(Text, nullable=True)

    # ── Timestamps ──
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    # Relations
    user = relationship("User", back_populates="jobs")
    account = relationship("UltraAccount", back_populates="jobs")

    def __repr__(self):
        return f"<Job #{self.id} [{self.status}] {self.prompt[:30]}>"


class UserRateLimit(Base):
    """Theo dõi rate limit per user"""
    __tablename__ = "user_rate_limits"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    active_jobs = Column(Integer, default=0)    # Số job đang active
    videos_today = Column(Integer, default=0)   # Tổng video hôm nay
    last_reset = Column(DateTime, default=datetime.utcnow)

    # Relations
    user = relationship("User", back_populates="rate_limit")


class BalanceHistory(Base):
    """Lịch sử thay đổi số dư"""
    __tablename__ = "balance_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    previous_amount = Column(Integer, nullable=False)
    changed_amount = Column(Integer, nullable=False)
    current_amount = Column(Integer, nullable=False)
    content = Column(Text, nullable=True)
    type = Column(String(50), nullable=False)  # deposit | generation | refund | admin
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemSetting(Base):
    """Cài đặt hệ thống (key-value)"""
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Indexes ──
Index("ix_jobs_user_status", GenerationJob.user_id, GenerationJob.status)
Index("ix_jobs_account_status", GenerationJob.account_id, GenerationJob.status)
Index("ix_accounts_status_health", UltraAccount.status, UltraAccount.health_score)


class SubscriptionPlan(Base):
    """Gói đăng ký dịch vụ"""
    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)          # "Starter", "Pro", "Enterprise"
    description = Column(Text, nullable=True)           # Mô tả gói
    credits = Column(Integer, nullable=False)            # Số credit cấp
    price = Column(Integer, nullable=False)              # Giá (VNĐ)
    duration_days = Column(Integer, default=30)          # Thời hạn (ngày)
    max_concurrent = Column(Integer, default=4)          # Max video cùng lúc
    features = Column(JSON, default=dict)                # Tính năng bổ sung
    is_active = Column(Boolean, default=True)            # Hiện/ẩn gói
    sort_order = Column(Integer, default=0)              # Thứ tự hiển thị
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Plan {self.name} — {self.credits}cr/{self.price}đ>"
