"""
Pydantic Schemas — Request/Response validation
Hỗ trợ cả Video + Image generation, Bulk prompts
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


# ═══════════════════════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=4, max_length=100)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=4, max_length=100)
    email: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    role: str
    balance: int


# ═══════════════════════════════════════════════════════════════════════════════
# GENERATION — Video + Image
# ═══════════════════════════════════════════════════════════════════════════════

class AspectRatio(str, Enum):
    LANDSCAPE = "16:9"
    FOUR_THREE = "4:3"
    SQUARE = "1:1"
    THREE_FOUR = "3:4"
    PORTRAIT = "9:16"


class MediaModel(str, Enum):
    # Video models
    VEO31_FAST = "veo31_fast"
    VEO31_LITE = "veo31_lite"
    VEO31_QUALITY = "veo31_quality"
    VEO31_FAST_LP = "veo31_fast_lp"
    VEO2_FAST = "veo2_fast"
    VEO2_QUALITY = "veo2_quality"
    # Image models
    NANO_BANANA_2 = "nano_banana_2"
    NANO_BANANA_PRO = "nano_banana_pro"
    IMAGEN_4 = "imagen_4"

# Backward compat alias
VideoModel = MediaModel


class GenerateRequest(BaseModel):
    """Request tạo video/ảnh mới (single prompt)"""
    prompt: str = Field(min_length=1, max_length=5000)
    aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE
    number_of_outputs: int = Field(default=1, ge=1, le=4)
    video_model: MediaModel = MediaModel.VEO31_FAST
    resolution: str = Field(default="720", pattern="^(720|1080|4k)$")


class BulkGenerateRequest(BaseModel):
    """Request tạo hàng loạt (nhiều prompt)"""
    prompts: list[str] = Field(min_length=1, max_length=100)
    aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE
    number_of_outputs: int = Field(default=1, ge=1, le=4)
    video_model: MediaModel = MediaModel.VEO31_FAST
    resolution: str = Field(default="720", pattern="^(720|1080|4k)$")


class GenerateResponse(BaseModel):
    """Response sau khi submit job(s)"""
    success: bool
    job_id: int                          # ID job đầu tiên
    job_ids: list[int] = []              # Tất cả job IDs
    batch_id: Optional[str] = None
    status: str
    cost: int
    remaining_balance: int
    queued_count: int = 0                # Số job vào hàng chờ
    message: Optional[str] = None


class JobStatusResponse(BaseModel):
    """Trạng thái 1 job"""
    id: int
    status: str
    progress_percent: int
    prompt: str
    model_key: Optional[str] = None
    media_type: str = "video"            # "video" | "image"
    video_url: Optional[str] = None
    r2_url: Optional[str] = None
    media_id: Optional[str] = None
    thumbnail_url: Optional[str] = None  # For images
    error: Optional[str] = None
    cost: int = 0
    upscale_status: Optional[str] = None  # "processing" | "completed" | None
    upscale_url: Optional[str] = None     # URL after upscale done
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class JobListResponse(BaseModel):
    """Danh sách jobs"""
    jobs: list[JobStatusResponse]
    total: int
    queue_count: int = 0                 # Số job đang chờ


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN
# ═══════════════════════════════════════════════════════════════════════════════

class AddAccountRequest(BaseModel):
    """Thêm tài khoản Ultra"""
    email: str
    password: str
    totp_secret: Optional[str] = None
    bearer_token: Optional[str] = None
    proxy_url: Optional[str] = None
    flow_project_url: Optional[str] = None


class AccountStatusResponse(BaseModel):
    """Trạng thái 1 account"""
    id: int
    email: str
    status: str
    is_enabled: bool = True
    health_score: int
    usage_count: int
    current_concurrent: int
    max_concurrent: int
    has_token: bool
    bearer_token: Optional[str] = None
    token_expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    last_refresh_at: Optional[datetime] = None
    proxy_url: Optional[str] = None
    flow_project_url: Optional[str] = None
    cookies: Optional[str] = None


class PoolStatsResponse(BaseModel):
    """Thống kê tổng pool"""
    total_accounts: int
    healthy_accounts: int
    total_capacity: int
    total_used: int
    available: int
    avg_health: int
    accounts: list[AccountStatusResponse]


class UpdateTokenRequest(BaseModel):
    """Cập nhật Bearer Token thủ công"""
    bearer_token: str = Field(min_length=10)
    expires_in_minutes: int = Field(default=180, ge=5, le=360)


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════════

class WSProgressEvent(BaseModel):
    """Event progress gửi qua WebSocket"""
    type: str  # progress | completed | failed | queued
    job_id: int
    status: str
    progress_percent: int = 0
    video_url: Optional[str] = None
    media_type: str = "video"
    error: Optional[str] = None
