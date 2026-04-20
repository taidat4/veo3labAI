"""
Veo3Lab Backend — FastAPI Main Application
=================================================
Pure HTTP Bearer Token architecture — KHÔNG dùng browser.

Khởi động:
  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, close_redis, get_redis

settings = get_settings()

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ultraflow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/Shutdown lifecycle"""
    logger.info("[START] Veo3Lab Backend starting...")

    # ── Startup ──
    # Import deposit models so their tables get registered with Base
    from app.routes.deposit import PendingDeposit, BankTransaction, ensure_deposit_tables  # noqa
    await init_db()
    await ensure_deposit_tables()
    logger.info("[OK] Database initialized")

    # Auto-migrate: add new columns to existing DB
    await _auto_migrate()

    redis = await get_redis()
    logger.info(f"[OK] Redis: {type(redis).__name__}")

    # Reset rate limit slots on startup (clear stale counts from crashed jobs)
    from app.rate_limiter import RateLimiter
    rate_limiter = RateLimiter(redis)
    await rate_limiter.reset_all()
    logger.info("[OK] Rate limit slots reset")

    # Cleanup stuck jobs from previous sessions
    from app.async_worker import cleanup_stuck_jobs
    await cleanup_stuck_jobs(max_age_minutes=10)
    logger.info("[OK] Stuck jobs cleaned up")

    logger.info(f"[OK] Server ready at http://localhost:{settings.PORT}")
    logger.info(f"[DOCS] http://localhost:{settings.PORT}/docs")

    yield

    # ── Shutdown ──
    logger.info("[STOP] Shutting down...")
    await close_redis()
    logger.info("[BYE] Goodbye!")


async def _auto_migrate():
    """Add new columns to existing tables (safe for SQLite)"""
    from app.database import engine

    migrations = [
        ("ultra_accounts", "flow_project_url", "VARCHAR(500)"),
        ("users", "api_key", "VARCHAR(64)"),
        ("users", "plan_id", "INTEGER"),
        ("users", "plan_expires_at", "DATETIME"),
    ]

    async with engine.begin() as conn:
        for table, column, col_type in migrations:
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                    )
                )
                logger.info(f"[MIGRATE] Added {table}.{column}")
            except Exception:
                pass  # Column already exists

        # Create subscription_plans table if not exists
        try:
            await conn.execute(__import__("sqlalchemy").text("""
                CREATE TABLE IF NOT EXISTS subscription_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    credits INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    duration_days INTEGER DEFAULT 30,
                    max_concurrent INTEGER DEFAULT 4,
                    features JSON,
                    is_active BOOLEAN DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """))
            logger.info("[MIGRATE] subscription_plans table ensured")
        except Exception:
            pass

        # Seed 4 default plans if empty
        try:
            count = (await conn.execute(__import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM subscription_plans"
            ))).scalar()
            if count == 0:
                plans = [
                    ("Free", "Dùng thử miễn phí", 5, 0, 0, 2, '["5 credits miễn phí","2 video đồng thời","720p"]', 1),
                    ("Basic", "Gói cơ bản cho cá nhân", 50, 99000, 30, 4, '["50 credits/tháng","4 video đồng thời","1080p","Hỗ trợ email"]', 2),
                    ("Pro", "Gói chuyên nghiệp", 200, 299000, 30, 8, '["200 credits/tháng","8 video đồng thời","1080p + 4K upscale","Hỗ trợ ưu tiên","API access"]', 3),
                    ("Enterprise", "Gói doanh nghiệp", 1000, 999000, 30, 20, '["1000 credits/tháng","20 video đồng thời","4K upscale","Hỗ trợ 24/7","API không giới hạn","Tài khoản team"]', 4),
                ]
                for name, desc, credits, price, days, conc, features, sort in plans:
                    await conn.execute(__import__("sqlalchemy").text(
                        "INSERT INTO subscription_plans (name, description, credits, price, duration_days, max_concurrent, features, is_active, sort_order) "
                        "VALUES (:n, :d, :c, :p, :dd, :mc, :f, 1, :s)"
                    ), {"n": name, "d": desc, "c": credits, "p": price, "dd": days, "mc": conc, "f": features, "s": sort})
                logger.info("[SEED] 4 default subscription plans created")
        except Exception as e:
            logger.warning(f"[SEED] Plans seed skipped: {e}")



# ═══════════════════════════════════════════════════════════════════════════════
# APP
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Veo3Lab — Video Generation API",
    description="Pure HTTP backend cho dịch vụ resell Google Flow Veo 3.1",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://veo3labai.com",
        "https://www.veo3labai.com",
        "https://veo3lab.com",
        "https://www.veo3lab.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routes ──
from app.routes.auth import router as auth_router
from app.routes.generate import router as generate_router
from app.routes.video import router as video_router
from app.routes.admin import router as admin_router
from app.routes.websocket import router as ws_router
from app.routes.public_api import router as public_api_router

app.include_router(auth_router)
app.include_router(generate_router)
app.include_router(video_router)
app.include_router(admin_router)
app.include_router(ws_router)
app.include_router(public_api_router)

# ── Deposit / Payment ──
from app.routes.deposit import router as deposit_router
app.include_router(deposit_router)

# ── Static files (upscaled videos) ──
import os
from fastapi.staticfiles import StaticFiles
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(os.path.join(static_dir, "upscaled"), exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ── Health check ──
@app.get("/health")
async def health():
    redis = await get_redis()
    redis_ok = await redis.ping()
    return {
        "status": "ok",
        "redis": "ok" if redis_ok else "error",
    }


@app.get("/")
async def root():
    return {
        "app": "Veo3Lab API",
        "version": "1.0.0",
        "docs": "/docs",
    }
