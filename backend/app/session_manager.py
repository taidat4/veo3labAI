"""
Session Manager — Quản lý Bearer Token cho tất cả acc Ultra
===================================================================
Module quan trọng nhất của hệ thống.

Chức năng:
1. Lưu/cache Bearer Token trong Redis (TTL 40 phút)
2. Round-robin chọn account healthy
3. Auto-refresh token trước khi hết hạn
4. Health check định kỳ
5. Auto-failover khi account bị ban/expired

Flow token:
- Admin nhập Bearer Token thủ công (từ DevTools, ya29.xxx)
- System lưu vào Redis + DB
- Background task kiểm tra token còn sống mỗi 5 phút
- Trước khi expire → trigger refresh (CapSolver + HTTP)
- Nếu fail → mark expired → tự động chuyển sang acc khác

⚠️ Google OAuth2 login qua HTTP thuần (không browser) rất khó:
   - Cần JS execution + reCAPTCHA
   - Nên dùng phương pháp: nhập token thủ công lần đầu
   - Auto-refresh bằng OAuth2 refresh token (nếu có)
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import httpx
try:
    from redis.asyncio import Redis as AsyncRedis
except ImportError:
    AsyncRedis = None
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.captcha_solver import solve_recaptcha
from app.models import UltraAccount, SessionData, AccountStatus
from app.database import async_session_factory

logger = logging.getLogger("veo3.session")
settings = get_settings()

# Redis key prefixes
TOKEN_PREFIX = "veo3:token:"          # {email} → bearer_token
TOKEN_EXPIRE_PREFIX = "veo3:token_exp:"  # {email} → expire timestamp
HEALTH_PREFIX = "veo3:health:"        # {email} → last_check_timestamp
ROUND_ROBIN_KEY = "veo3:rr_index"     # Round-robin counter


class SessionManager:
    """
    Quản lý session/token cho tất cả accounts Ultra.
    Sử dụng Redis làm cache nhanh, DB để persist.
    """

    def __init__(self, redis: AsyncRedis):
        self.redis = redis
        self._running = False
        self._refresh_task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None

    # ═══════════════════════════════════════════════════════════════════════════
    # TOKEN MANAGEMENT
    # ═══════════════════════════════════════════════════════════════════════════

    async def store_token(
        self,
        email: str,
        bearer_token: str,
        expires_in_minutes: int = 180,
        source: str = "manual",
    ):
        """
        Lưu Bearer Token cho 1 account.

        Args:
            email: Email tài khoản
            bearer_token: ya29.xxx token
            expires_in_minutes: Thời gian sống (phút)
            source: "manual" hoặc "auto-refresh"
        """
        expire_seconds = expires_in_minutes * 60
        expire_at = datetime.utcnow() + timedelta(minutes=expires_in_minutes)

        # Lưu vào Redis (tự expire)
        await self.redis.set(f"{TOKEN_PREFIX}{email}", bearer_token, ex=expire_seconds)
        await self.redis.set(f"{TOKEN_EXPIRE_PREFIX}{email}", expire_at.isoformat(), ex=expire_seconds)

        # Lưu vào DB (persist)
        async with async_session_factory() as session:
            stmt = (
                update(UltraAccount)
                .where(UltraAccount.email == email)
                .values(
                    bearer_token=bearer_token,
                    token_expires_at=expire_at,
                    token_source=source,
                    status="healthy",
                    health_score=100,
                    fail_count=0,
                    last_refresh_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            await session.execute(stmt)
            await session.commit()

        logger.info(f"✅ Token saved: {email} (source={source}, expires={expire_at})")

    async def get_token(self, email: str) -> str | None:
        """Lấy Bearer Token từ Redis cache (nhanh) hoặc DB (fallback)"""
        # Try Redis first
        token = await self.redis.get(f"{TOKEN_PREFIX}{email}")
        if token:
            return token

        # Fallback: load từ DB
        async with async_session_factory() as session:
            result = await session.execute(
                select(UltraAccount).where(UltraAccount.email == email)
            )
            account = result.scalar_one_or_none()
            if account and account.bearer_token:
                # Check expiry
                if account.token_expires_at and account.token_expires_at > datetime.utcnow():
                    # Re-cache vào Redis
                    remaining = (account.token_expires_at - datetime.utcnow()).total_seconds()
                    if remaining > 60:
                        await self.redis.setex(
                            f"{TOKEN_PREFIX}{email}",
                            int(remaining),
                            account.bearer_token,
                        )
                    return account.bearer_token

        return None

    async def invalidate_token(self, email: str, reason: str = "expired"):
        """Đánh dấu token expired (chỉ xóa Redis cache, giữ nguyên token trong DB)"""
        await self.redis.delete(f"{TOKEN_PREFIX}{email}")
        await self.redis.delete(f"{TOKEN_EXPIRE_PREFIX}{email}")

        async with async_session_factory() as session:
            stmt = (
                update(UltraAccount)
                .where(UltraAccount.email == email)
                .values(
                    status="expired",
                    updated_at=datetime.utcnow(),
                )
            )
            await session.execute(stmt)
            await session.commit()

        logger.warning(f"⚠️ Token marked expired: {email} (reason={reason}) — token vẫn giữ trong DB")

    # ═══════════════════════════════════════════════════════════════════════════
    # ACCOUNT SELECTION — Round-robin + health check
    # ═══════════════════════════════════════════════════════════════════════════

    async def get_healthy_account(self, exclude_emails: list[str] | None = None) -> dict | None:
        """
        Chọn account healthy theo round-robin, ưu tiên health score cao.

        Returns:
            {"email": ..., "token": ..., "proxy": ...} hoặc None
        """
        exclude = set(exclude_emails or [])

        async with async_session_factory() as session:
            result = await session.execute(
                select(UltraAccount)
                .where(
                    UltraAccount.status == "healthy",
                    UltraAccount.bearer_token.isnot(None),
                )
                .order_by(UltraAccount.current_concurrent.asc(), UltraAccount.usage_count.asc(), UltraAccount.health_score.desc())
            )
            accounts = result.scalars().all()

        if not accounts:
            logger.error("❌ Không có account healthy nào!")
            return None

        # Lọc exclude
        candidates = [a for a in accounts if a.email not in exclude]
        if not candidates:
            candidates = accounts  # Fallback

        # Round-robin index
        idx = await self.redis.incr(ROUND_ROBIN_KEY)
        selected = candidates[idx % len(candidates)]

        # Verify token
        token = await self.get_token(selected.email)
        if not token:
            # Token missing from Redis AND DB → skip this account, try next
            logger.warning(f"⚠️ No token for {selected.email}, skipping")
            exclude.add(selected.email)
            return await self.get_healthy_account(list(exclude))

        return {
            "email": selected.email,
            "token": token,
            "proxy": selected.proxy_url,
            "account_id": selected.id,
        }

    async def report_success(self, email: str):
        """Báo cáo request thành công → tăng health"""
        async with async_session_factory() as session:
            stmt = (
                update(UltraAccount)
                .where(UltraAccount.email == email)
                .values(
                    fail_count=0,
                    health_score=UltraAccount.health_score + 1,
                    usage_count=UltraAccount.usage_count + 1,
                    last_used_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            await session.execute(stmt)
            # Cap ở 100
            await session.execute(
                update(UltraAccount)
                .where(UltraAccount.email == email, UltraAccount.health_score > 100)
                .values(health_score=100)
            )
            await session.commit()

    async def report_failure(self, email: str, error: str = ""):
        """Báo cáo request fail → giảm health, có thể disable"""
        async with async_session_factory() as session:
            result = await session.execute(
                select(UltraAccount).where(UltraAccount.email == email)
            )
            account = result.scalar_one_or_none()
            if not account:
                return

            new_fail = account.fail_count + 1
            new_health = max(0, account.health_score - 10)
            new_status = account.status

            # 3 lần fail liên tiếp → mark expired
            if new_fail >= 3:
                new_status = "expired"
                await self.invalidate_token(email, f"too_many_failures: {error}")
                logger.error(f"💀 Account {email} expired after {new_fail} failures: {error}")

            stmt = (
                update(UltraAccount)
                .where(UltraAccount.email == email)
                .values(
                    fail_count=new_fail,
                    health_score=new_health,
                    status=new_status,
                    updated_at=datetime.utcnow(),
                )
            )
            await session.execute(stmt)
            await session.commit()

    # ═══════════════════════════════════════════════════════════════════════════
    # HEALTH CHECK — Verify token vẫn hoạt động
    # ═══════════════════════════════════════════════════════════════════════════

    async def health_check(self, email: str) -> bool:
        """
        Verify token bằng 1 lightweight API call.
        Gọi endpoint check status với operation_id fake → 200 = token OK, 401 = expired
        """
        token = await self.get_token(email)
        if not token:
            return False

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Gọi status check với dummy operation → nếu 200/400 = token OK, 401 = expired
                resp = await client.post(
                    f"{settings.FLOW_API_BASE}/v1/video:batchCheckAsyncVideoGenerationStatus",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "text/plain;charset=UTF-8",
                        "Origin": "https://labs.google",
                        "Referer": "https://labs.google/",
                    },
                    content=json.dumps({
                        "operations": [
                            {"operation": {"name": "health-check-probe"}, "status": "MEDIA_GENERATION_STATUS_PENDING"}
                        ]
                    }),
                )

                if resp.status_code == 401 or resp.status_code == 403:
                    logger.warning(f"⚠️ Token expired: {email} (HTTP {resp.status_code})")
                    await self.invalidate_token(email, f"http_{resp.status_code}")
                    return False

                # 200 hoặc 400 (bad operation_id) đều có nghĩa token còn sống
                await self.redis.setex(f"{HEALTH_PREFIX}{email}", 600, str(time.time()))

                async with async_session_factory() as session:
                    await session.execute(
                        update(UltraAccount)
                        .where(UltraAccount.email == email)
                        .values(last_health_check=datetime.utcnow())
                    )
                    await session.commit()

                return True

        except Exception as e:
            logger.error(f"❌ Health check failed: {email} — {e}")
            return False

    # ═══════════════════════════════════════════════════════════════════════════
    # BACKGROUND TASKS — Auto refresh + health check
    # ═══════════════════════════════════════════════════════════════════════════

    async def start_background_tasks(self):
        """Khởi động background tasks"""
        if self._running:
            return
        self._running = True
        self._refresh_task = asyncio.create_task(self._auto_refresh_loop())
        self._health_task = asyncio.create_task(self._health_check_loop())
        logger.info("🚀 Background tasks started (refresh + health check)")

    async def stop_background_tasks(self):
        """Dừng background tasks"""
        self._running = False
        if self._refresh_task:
            self._refresh_task.cancel()
        if self._health_task:
            self._health_task.cancel()
        logger.info("🛑 Background tasks stopped")

    async def _auto_refresh_loop(self):
        """
        Loop refresh token mỗi 35 phút cho tất cả acc.
        Token Google thường expire sau ~60 phút.
        Refresh ở phút 35 để có buffer an toàn.
        """
        while self._running:
            try:
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(UltraAccount).where(
                            UltraAccount.status.in_(["healthy", "expired"]),
                        )
                    )
                    accounts = result.scalars().all()

                for acc in accounts:
                    if not self._running:
                        break

                    # Kiểm tra token sắp hết hạn (< 10 phút)
                    expire_str = await self.redis.get(f"{TOKEN_EXPIRE_PREFIX}{acc.email}")
                    if expire_str:
                        expire_at = datetime.fromisoformat(expire_str)
                        remaining = (expire_at - datetime.utcnow()).total_seconds()
                        if remaining > 600:  # Còn > 10 phút → skip
                            continue

                    logger.info(f"🔄 Auto-refresh {acc.email}...")

                    # Thử refresh bằng CapSolver
                    try:
                        recaptcha_token = await solve_recaptcha(
                            action="generate",
                            proxy=acc.proxy_url,
                        )
                        if recaptcha_token:
                            logger.info(f"✅ Got reCAPTCHA token for {acc.email}")
                            # TODO: Implement token refresh via OAuth2 endpoint
                            # Đối với phiên bản đầu, admin phải nhập token thủ công
                        else:
                            logger.warning(f"⚠️ CapSolver failed for {acc.email}")
                    except Exception as e:
                        logger.error(f"❌ Refresh failed {acc.email}: {e}")

                    await asyncio.sleep(5)  # Delay giữa các acc

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Auto-refresh loop error: {e}")

            # Chờ 5 phút trước vòng tiếp
            await asyncio.sleep(300)

    async def _health_check_loop(self):
        """Loop health check mỗi 5 phút"""
        while self._running:
            try:
                async with async_session_factory() as session:
                    result = await session.execute(
                        select(UltraAccount).where(
                            UltraAccount.status == "healthy",
                        )
                    )
                    accounts = result.scalars().all()

                for acc in accounts:
                    if not self._running:
                        break
                    await self.health_check(acc.email)
                    await asyncio.sleep(2)  # Delay giữa các check

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Health check loop error: {e}")

            await asyncio.sleep(300)  # 5 phút

    # ═══════════════════════════════════════════════════════════════════════════
    # POOL STATS
    # ═══════════════════════════════════════════════════════════════════════════

    async def get_pool_stats(self) -> dict:
        """Lấy thống kê tổng quan pool accounts"""
        async with async_session_factory() as session:
            result = await session.execute(select(UltraAccount))
            accounts = result.scalars().all()

        total = len(accounts)
        healthy = sum(1 for a in accounts if a.status == "healthy")
        expired = sum(1 for a in accounts if a.status == "expired")
        banned = sum(1 for a in accounts if a.status == "banned")
        avg_health = (
            sum(a.health_score for a in accounts) // total if total > 0 else 0
        )

        account_list = []
        for acc in accounts:
            token = await self.get_token(acc.email)
            account_list.append({
                "id": acc.id,
                "email": acc.email,
                "status": acc.status or "unknown",
                "is_enabled": acc.is_enabled if hasattr(acc, 'is_enabled') else True,
                "health_score": acc.health_score,
                "usage_count": acc.usage_count,
                "current_concurrent": acc.current_concurrent,
                "max_concurrent": acc.max_concurrent,
                "has_token": bool(token),
                "bearer_token": token,  # Full token for admin to view/copy
                "token_expires_at": (acc.token_expires_at.isoformat() + "Z") if acc.token_expires_at else None,
                "last_used_at": (acc.last_used_at.isoformat() + "Z") if acc.last_used_at else None,
                "last_refresh_at": (acc.last_refresh_at.isoformat() + "Z") if acc.last_refresh_at else None,
                "proxy_url": acc.proxy_url,
                "flow_project_url": acc.flow_project_url,
                "cookies": acc.cookies,
            })

        return {
            "total_accounts": total,
            "healthy_accounts": healthy,
            "expired_accounts": expired,
            "banned_accounts": banned,
            "avg_health": avg_health,
            "accounts": account_list,
        }
