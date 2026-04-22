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

    # Auto-cleanup old upscaled video cache (files older than 24h)
    _cleanup_old_files()

    logger.info(f"[OK] Server ready at http://localhost:{settings.PORT}")
    logger.info(f"[DOCS] http://localhost:{settings.PORT}/docs")

    yield

    # ── Shutdown ──
    logger.info("[STOP] Shutting down...")
    await close_redis()
    logger.info("[BYE] Goodbye!")


def _cleanup_old_files():
    """Auto-cleanup old cached files to prevent disk bloat."""
    import os
    import time

    base_dir = os.path.dirname(os.path.dirname(__file__))
    max_age = 24 * 3600  # 24 hours
    now = time.time()
    total_cleaned = 0

    # 1. Clean old upscaled videos (backend/static/upscaled/)
    upscaled_dir = os.path.join(base_dir, "static", "upscaled")
    if os.path.exists(upscaled_dir):
        for f in os.listdir(upscaled_dir):
            fpath = os.path.join(upscaled_dir, f)
            try:
                if os.path.isfile(fpath) and (now - os.path.getmtime(fpath)) > max_age:
                    size = os.path.getsize(fpath)
                    os.remove(fpath)
                    total_cleaned += size
            except Exception:
                pass

    # 2. Clean __pycache__ dirs
    for root, dirs, files in os.walk(base_dir):
        if "__pycache__" in dirs:
            cache_dir = os.path.join(root, "__pycache__")
            try:
                import shutil
                size = sum(os.path.getsize(os.path.join(cache_dir, f)) for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f)))
                shutil.rmtree(cache_dir, ignore_errors=True)
                total_cleaned += size
            except Exception:
                pass

    if total_cleaned > 0:
        logger.info(f"[CLEANUP] Freed {total_cleaned / 1024 / 1024:.1f} MB of old cache files")
    else:
        logger.info("[CLEANUP] No old files to clean")

async def _auto_migrate():
    """Add new columns to existing tables (safe for SQLite)"""
    from app.database import engine

    migrations = [
        ("ultra_accounts", "flow_project_url", "VARCHAR(500)"),
        ("users", "api_key", "VARCHAR(64)"),
        ("users", "plan_id", "INTEGER"),
        ("users", "plan_expires_at", "TIMESTAMP"),
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
            # Use SERIAL for PostgreSQL, fallback works for SQLite too
            from app.database import is_sqlite
            pk_type = "INTEGER PRIMARY KEY AUTOINCREMENT" if is_sqlite else "SERIAL PRIMARY KEY"
            bool_default = "DEFAULT 1" if is_sqlite else "DEFAULT TRUE"
            await conn.execute(__import__("sqlalchemy").text(f"""
                CREATE TABLE IF NOT EXISTS subscription_plans (
                    id {pk_type},
                    name VARCHAR(100) NOT NULL,
                    description TEXT,
                    credits INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    duration_days INTEGER DEFAULT 30,
                    max_concurrent INTEGER DEFAULT 4,
                    features TEXT,
                    is_active BOOLEAN {bool_default},
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
            logger.info("[MIGRATE] subscription_plans table ensured")
        except Exception:
            pass

        # Seed 6 plans (5 subscription + 1 credit pack)
        try:
            count = (await conn.execute(__import__("sqlalchemy").text(
                "SELECT COUNT(*) FROM subscription_plans"
            ))).scalar()
            if count == 0 or count == 4:
                # Clear old plans if exactly 4 (old seed)
                if count == 4:
                    await conn.execute(__import__("sqlalchemy").text(
                        "DELETE FROM subscription_plans"
                    ))
                plans = [
                    ("Dùng thử", "Trải nghiệm miễn phí", 10, 0, 7, 2, '["10 credits","2 video đồng thời","720p"]', 1),
                    ("Cơ bản", "Gói cơ bản cho cá nhân", 100, 50000, 30, 4, '["100 credits/tháng","4 video đồng thời","1080p"]', 2),
                    ("Tiêu chuẩn", "Gói phổ biến nhất", 500, 200000, 30, 6, '["500 credits/tháng","6 video đồng thời","1080p + Upscale"]', 3),
                    ("Cao cấp", "Gói chuyên nghiệp", 2000, 500000, 30, 10, '["2000 credits/tháng","10 video đồng thời","4K Upscale","Hỗ trợ ưu tiên"]', 4),
                    ("Doanh nghiệp", "Không giới hạn sáng tạo", 10000, 1500000, 30, 20, '["10000 credits/tháng","20 video đồng thời","4K Upscale","API access","Hỗ trợ 24/7"]', 5),
                    ("Mua Credit", "10.000đ = 1.000 credits", 1000, 10000, 0, 0, '["Mua thêm credit","Không thời hạn","Dùng ngay"]', 6),
                ]
                for name, desc, credits, price, days, conc, features, sort in plans:
                    await conn.execute(__import__("sqlalchemy").text(
                        "INSERT INTO subscription_plans (name, description, credits, price, duration_days, max_concurrent, features, is_active, sort_order) "
                        "VALUES (:n, :d, :c, :p, :dd, :mc, :f, 1, :s)"
                    ), {"n": name, "d": desc, "c": credits, "p": price, "dd": days, "mc": conc, "f": features, "s": sort})
                logger.info("[SEED] 6 subscription plans created (5 tiers + 1 credit pack)")
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

# ── Upload (Image-to-Video) ──
from app.routes.upload import router as upload_router
app.include_router(upload_router)

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
