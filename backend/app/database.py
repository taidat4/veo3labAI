"""
Database connection — async SQLAlchemy 2.0 + Redis (optional)
Hỗ trợ SQLite cho dev, PostgreSQL cho production
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

# ── Detect SQLite vs PostgreSQL ──
# Railway gives postgres:// but SQLAlchemy needs postgresql+asyncpg://
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif db_url.startswith("postgresql://"):
    db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
is_sqlite = "sqlite" in db_url

# ── Async SQLAlchemy engine ──
engine_kwargs = {
    "echo": False,
}
if not is_sqlite:
    engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 10,
        "pool_pre_ping": True,
    })

engine = create_async_engine(db_url, **engine_kwargs)

# ── Session factory ──
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── Base class cho models ──
class Base(DeclarativeBase):
    pass


# ── Dependency: lấy DB session cho FastAPI ──
async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ═══════════════════════════════════════════════════════
# Redis — Optional (dùng dict in-memory nếu không có Redis)
# ═══════════════════════════════════════════════════════

class FakeRedis:
    """In-memory mock Redis cho dev (không cần Redis server)"""
    def __init__(self):
        self._data = {}
        self._pubsub_handlers = {}

    async def ping(self):
        return True

    async def get(self, key):
        return self._data.get(key)

    async def set(self, key, value, ex=None):
        self._data[key] = value

    async def setex(self, key, seconds, value):
        """Set key with expiration (in-memory just stores, ignores TTL)"""
        self._data[key] = value

    async def delete(self, key):
        self._data.pop(key, None)

    async def exists(self, key):
        return 1 if key in self._data else 0

    async def keys(self, pattern="*"):
        if pattern == "*":
            return list(self._data.keys())
        import fnmatch
        return [k for k in self._data if fnmatch.fnmatch(k, pattern)]

    async def incr(self, key):
        self._data[key] = self._data.get(key, 0) + 1
        return self._data[key]

    async def decr(self, key):
        self._data[key] = self._data.get(key, 0) - 1
        return self._data[key]

    async def expire(self, key, seconds):
        pass

    async def ttl(self, key):
        return -1

    async def hset(self, name, key=None, value=None, mapping=None):
        if name not in self._data:
            self._data[name] = {}
        if mapping:
            self._data[name].update(mapping)
        elif key is not None:
            self._data[name][key] = value

    async def hget(self, name, key):
        return self._data.get(name, {}).get(key)

    async def hgetall(self, name):
        return self._data.get(name, {})

    async def publish(self, channel, message):
        pass

    async def close(self):
        pass

    async def scan_iter(self, match="*"):
        import fnmatch
        for k in list(self._data.keys()):
            if fnmatch.fnmatch(k, match):
                yield k

    def pubsub(self):
        return FakePubSub()


class FakePubSub:
    async def subscribe(self, *channels):
        pass

    async def listen(self):
        # Yield nothing forever
        while True:
            import asyncio
            await asyncio.sleep(3600)
            yield {"type": "message", "data": "{}"}

    async def close(self):
        pass


_redis = None


async def get_redis():
    """Lấy Redis connection — trả về FakeRedis nếu không config"""
    global _redis
    if _redis is None:
        if settings.REDIS_URL:
            try:
                from redis.asyncio import Redis as AsyncRedis
                _redis = AsyncRedis.from_url(
                    settings.REDIS_URL,
                    decode_responses=True,
                    max_connections=50,
                )
                await _redis.ping()
            except Exception:
                print("[WARN] Redis connection failed, using FakeRedis (in-memory)")
                _redis = FakeRedis()
        else:
            print("[INFO] REDIS_URL empty, using FakeRedis (in-memory)")
            _redis = FakeRedis()
    return _redis


async def close_redis():
    global _redis
    if _redis:
        await _redis.close()
        _redis = None


async def init_db():
    """Tạo tất cả bảng + auto-migrate"""
    from sqlalchemy import text as sa_text

    # ── Step 1: Create all tables first (for new deployments) ──
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[DB] ✅ All tables created/verified")

    # ── Step 2: Auto-migrate credits column if missing ──
    try:
        async with engine.begin() as conn:
            if is_sqlite:
                # SQLite: check pragma
                result = await conn.execute(sa_text("PRAGMA table_info(users)"))
                columns = [row[1] for row in result.fetchall()]
                if "credits" not in columns:
                    await conn.execute(sa_text(
                        "ALTER TABLE users ADD COLUMN credits INTEGER DEFAULT 0"
                    ))
                    print("[MIGRATE] ✅ Added 'credits' column")
                else:
                    print("[MIGRATE] credits column exists — OK")
            else:
                # PostgreSQL: IF NOT EXISTS
                await conn.execute(sa_text(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS credits INTEGER DEFAULT 0"
                ))
                print("[MIGRATE] ✅ credits column ready")
    except Exception as e:
        print(f"[MIGRATE] credits migration: {e}")
