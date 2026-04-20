"""
Rate Limiter — Redis-based rate limiting

Quản lý:
- 1 account Ultra: max 40 video đồng thời
- 1 user: max 8 video đồng thời
- Queue chờ khi vượt limit
"""

import logging
try:
    from redis.asyncio import Redis as AsyncRedis
except ImportError:
    AsyncRedis = None
from app.config import get_settings

logger = logging.getLogger("veo3.rate_limiter")
settings = get_settings()

# Redis key prefixes
ACCOUNT_LOCK_PREFIX = "veo3:acc_lock:"    # {email} → current count
USER_LOCK_PREFIX = "veo3:user_lock:"      # {user_id} → current count
QUEUE_KEY = "veo3:job_queue"              # Sorted set: job_id → timestamp


class RateLimiter:
    """Redis-based rate limiter cho video generation"""

    def __init__(self, redis: AsyncRedis):
        self.redis = redis

    # ── Account Rate Limit ──

    async def can_account_accept(self, email: str) -> bool:
        """Kiểm tra account có thể nhận thêm job không"""
        key = f"{ACCOUNT_LOCK_PREFIX}{email}"
        current = await self.redis.get(key)
        count = int(current) if current else 0
        return count < settings.MAX_VIDEOS_PER_ACCOUNT

    async def acquire_account_slot(self, email: str) -> bool:
        """Chiếm 1 slot cho account, trả False nếu đầy"""
        key = f"{ACCOUNT_LOCK_PREFIX}{email}"
        current = await self.redis.incr(key)
        # Set TTL 30 phút (auto cleanup nếu worker crash)
        await self.redis.expire(key, 1800)

        if current > settings.MAX_VIDEOS_PER_ACCOUNT:
            await self.redis.decr(key)
            return False
        return True

    async def release_account_slot(self, email: str):
        """Giải phóng 1 slot khi job xong"""
        key = f"{ACCOUNT_LOCK_PREFIX}{email}"
        current = await self.redis.decr(key)
        # Không cho âm
        if current < 0:
            await self.redis.set(key, 0)

    async def get_account_usage(self, email: str) -> int:
        """Lấy số slot đang dùng"""
        key = f"{ACCOUNT_LOCK_PREFIX}{email}"
        val = await self.redis.get(key)
        return int(val) if val else 0

    # ── User Rate Limit ──

    async def can_user_generate(self, user_id: int) -> bool:
        """Kiểm tra user có thể tạo thêm video không"""
        key = f"{USER_LOCK_PREFIX}{user_id}"
        current = await self.redis.get(key)
        count = int(current) if current else 0
        return count < settings.MAX_VIDEOS_PER_USER

    async def acquire_user_slot(self, user_id: int) -> bool:
        """Chiếm 1 slot cho user"""
        key = f"{USER_LOCK_PREFIX}{user_id}"
        current = await self.redis.incr(key)
        await self.redis.expire(key, 1800)

        if current > settings.MAX_VIDEOS_PER_USER:
            await self.redis.decr(key)
            return False
        return True

    async def release_user_slot(self, user_id: int):
        """Giải phóng 1 slot user"""
        key = f"{USER_LOCK_PREFIX}{user_id}"
        current = await self.redis.decr(key)
        if current < 0:
            await self.redis.set(key, 0)

    async def get_user_usage(self, user_id: int) -> int:
        """Số video đang active của user"""
        key = f"{USER_LOCK_PREFIX}{user_id}"
        val = await self.redis.get(key)
        return int(val) if val else 0

    # ── Queue Info ──

    async def get_queue_position(self, job_id: int) -> int:
        """Vị trí trong queue (-1 nếu không có)"""
        rank = await self.redis.zrank(QUEUE_KEY, str(job_id))
        return rank if rank is not None else -1

    async def get_queue_length(self) -> int:
        """Tổng số job trong queue"""
        return await self.redis.zcard(QUEUE_KEY)

    # ── Cleanup ──

    async def reset_account(self, email: str):
        """Reset lock counter cho account (dùng khi restart)"""
        key = f"{ACCOUNT_LOCK_PREFIX}{email}"
        await self.redis.delete(key)

    async def reset_user(self, user_id: int):
        """Reset lock counter cho user"""
        key = f"{USER_LOCK_PREFIX}{user_id}"
        await self.redis.delete(key)

    async def reset_all(self):
        """Reset tất cả locks (dùng khi khởi động lại)"""
        # Scan và xóa tất cả keys với prefix
        async for key in self.redis.scan_iter(f"{ACCOUNT_LOCK_PREFIX}*"):
            await self.redis.delete(key)
        async for key in self.redis.scan_iter(f"{USER_LOCK_PREFIX}*"):
            await self.redis.delete(key)
        logger.info("🔄 Đã reset tất cả rate limit locks")
