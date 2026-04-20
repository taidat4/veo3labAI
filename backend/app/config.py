"""
Cấu hình ứng dụng — đọc từ .env
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Optional


class Settings(BaseSettings):
    """Tất cả config đọc từ environment variables"""

    # ── Database ──
    DATABASE_URL: str = "sqlite+aiosqlite:///./veo3.db"
    DATABASE_URL_SYNC: str = ""

    @property
    def sync_db_url(self) -> str:
        """Derive sync database URL from async URL"""
        if self.DATABASE_URL_SYNC:
            return self.DATABASE_URL_SYNC
        url = self.DATABASE_URL
        if "aiosqlite" in url:
            return url.replace("sqlite+aiosqlite", "sqlite")
        if "asyncpg" in url:
            return url.replace("postgresql+asyncpg", "postgresql")
        return url

    # ── Redis ──
    REDIS_URL: str = ""

    # ── JWT Auth ──
    JWT_SECRET: str = "change-this-secret-key"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 giờ

    # ── Admin (chỉ cần key để vào dashboard, không cần username/password) ──
    ADMIN_SECRET_KEY: str = "VEO3-ADM-00B85D5FEF95278C1EA4DF9DAB9E5CCF"

    # ── Captcha — Dual Provider (legacy, not needed with NanoAI) ──
    CAPTCHA_PROVIDER: str = "capsolver"  # "capsolver" | "2captcha" | "omocaptcha"
    TWOCAPTCHA_API_KEY: str = ""
    OMOCAPTCHA_API_KEY: str = ""
    CAPSOLVER_API_KEY: str = ""

    # ── NanoAI Proxy (handles captcha + sends to Google) ──
    NANOAI_API_KEY: str = ""
    NANOAI_BASE_URL: str = "https://flow-api.nanoai.pics/api/fix"
    # Generation provider: "nanoai" = proxy via NanoAI, "direct" = direct to Google + captcha
    GENERATION_PROVIDER: str = "nanoai"

    # ── Google reCAPTCHA (only for direct mode) ──
    RECAPTCHA_SITE_KEY: str = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"
    RECAPTCHA_PAGE_URL: str = "https://labs.google/fx/vi/tools/flow"

    # ── Proxy VN ──
    PROXY_LIST: str = ""

    # ── Cloudflare R2 ──
    R2_ENDPOINT: str = ""
    R2_ACCESS_KEY: str = ""
    R2_SECRET_KEY: str = ""
    R2_BUCKET: str = "veo3-videos"
    R2_PUBLIC_URL: str = ""

    # ── MBBank Payment ──
    MBBANK_API_URL: str = "https://apicanhan.com/api/mbbankv3"
    MBBANK_API_KEY: str = ""
    MBBANK_USERNAME: str = ""
    MBBANK_PASSWORD: str = ""
    MBBANK_ACCOUNT: str = ""
    MBBANK_NAME: str = "MB Bank"

    # ── Google Flow API ──
    FLOW_API_BASE: str = "https://aisandbox-pa.googleapis.com"

    # ── Rate Limits ──
    MAX_VIDEOS_PER_ACCOUNT: int = 40       # Max total per account cycle
    ACCOUNT_ROTATE_THRESHOLD: int = 20     # Rotate after N videos
    MAX_VIDEOS_PER_USER: int = 8           # Max concurrent per user
    MAX_USERS_PER_ACCOUNT: int = 5         # Max users sharing 1 account

    # ── Worker ──
    WORKER_CONCURRENCY: int = 5
    POLL_INTERVAL_SECONDS: int = 4
    MAX_CONSECUTIVE_FAILURES: int = 3

    # ── Server ──
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    @property
    def proxy_list(self) -> list[str]:
        """Parse danh sách proxy từ env"""
        if not self.PROXY_LIST:
            return []
        return [p.strip() for p in self.PROXY_LIST.split(",") if p.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
