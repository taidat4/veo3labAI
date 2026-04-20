"""
Veo Worker — Background video generation via Celery

Flow hoàn chỉnh:
1. Nhận job từ queue (prompt + params)
2. Chọn account healthy (round-robin)
3. Build API request (veo_template)
4. Gửi request → nhận operation_id
5. Poll status mỗi 4 giây
6. Estimate progress % → push qua Redis pub/sub
7. Khi xong → download video → upload R2
8. Update DB → notify user qua WebSocket
"""

import asyncio
import json
import logging
import time
from datetime import datetime

import httpx
try:
    from redis import Redis as SyncRedis
except ImportError:
    SyncRedis = None

from celery_app import celery_app
from app.config import get_settings
from app.veo_template import (
    GENERATE_URL, STATUS_URL,
    build_generate_request, build_status_request,
    build_auth_headers, parse_generate_response, parse_status_response,
    MODEL_PRICING,
)

logger = logging.getLogger("veo3.worker")
settings = get_settings()

# Redis sync client (Celery workers chạy sync)
_redis: SyncRedis | None = None


class FakeSyncRedis:
    def __init__(self):
        self._data = {}
    def get(self, key):
        return self._data.get(key)
    def set(self, key, value, ex=None):
        self._data[key] = value
    def delete(self, key):
        self._data.pop(key, None)
    def incr(self, key):
        self._data[key] = self._data.get(key, 0) + 1
        return self._data[key]
    def decr(self, key):
        self._data[key] = self._data.get(key, 0) - 1
        return self._data[key]
    def publish(self, channel, message):
        pass


def get_sync_redis():
    global _redis
    if _redis is None:
        if SyncRedis and settings.REDIS_URL:
            try:
                _redis = SyncRedis.from_url(settings.REDIS_URL, decode_responses=True)
                _redis.ping()
            except Exception:
                _redis = FakeSyncRedis()
        else:
            _redis = FakeSyncRedis()
    return _redis


# Redis pub/sub channel
PROGRESS_CHANNEL = "veo3:progress"


def publish_progress(user_id: int, job_id: int, data: dict):
    """Publish progress event qua Redis pub/sub → WebSocket sẽ nhận"""
    redis = get_sync_redis()
    event = {
        "user_id": user_id,
        "job_id": job_id,
        **data,
    }
    redis.publish(PROGRESS_CHANNEL, json.dumps(event))


def update_job_db(job_id: int, **kwargs):
    """Update job trong DB (sync, dùng trong Celery)"""
    from sqlalchemy import create_engine, update
    from sqlalchemy.orm import Session
    from app.models import GenerationJob

    engine = create_engine(settings.sync_db_url)
    with Session(engine) as session:
        stmt = update(GenerationJob).where(GenerationJob.id == job_id).values(**kwargs)
        session.execute(stmt)
        session.commit()


def get_account_token(exclude_emails: list[str] | None = None) -> dict | None:
    """Lấy account healthy + token (sync version cho Celery)"""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.models import UltraAccount, AccountStatus

    engine = create_engine(settings.sync_db_url)
    redis = get_sync_redis()

    with Session(engine) as session:
        query = (
            select(UltraAccount)
            .where(
                UltraAccount.status == "healthy",
                UltraAccount.bearer_token.isnot(None),
            )
            .order_by(UltraAccount.health_score.desc(), UltraAccount.usage_count.asc())
        )
        accounts = session.execute(query).scalars().all()

    if not accounts:
        return None

    exclude = set(exclude_emails or [])
    candidates = [a for a in accounts if a.email not in exclude]
    if not candidates:
        candidates = accounts

    # Round-robin
    idx = int(redis.incr("veo3:worker_rr") or 0)
    selected = candidates[idx % len(candidates)]

    # Token từ Redis cache hoặc DB
    token = redis.get(f"veo3:token:{selected.email}")
    if not token:
        token = selected.bearer_token

    if not token:
        return None

    return {
        "email": selected.email,
        "token": token,
        "proxy": selected.proxy_url,
        "account_id": selected.id,
    }


def report_account_result(email: str, success: bool, error: str = ""):
    """Report kết quả → cập nhật health score"""
    from sqlalchemy import create_engine, update, select
    from sqlalchemy.orm import Session
    from app.models import UltraAccount, AccountStatus

    engine = create_engine(settings.sync_db_url)
    with Session(engine) as session:
        if success:
            session.execute(
                update(UltraAccount)
                .where(UltraAccount.email == email)
                .values(
                    fail_count=0,
                    usage_count=UltraAccount.usage_count + 1,
                    last_used_at=datetime.utcnow(),
                )
            )
        else:
            acc = session.execute(
                select(UltraAccount).where(UltraAccount.email == email)
            ).scalar_one_or_none()
            if acc:
                new_fail = acc.fail_count + 1
                new_health = max(0, acc.health_score - 10)
                values = {
                    "fail_count": new_fail,
                    "health_score": new_health,
                }
                if new_fail >= 3:
                    values["status"] = "expired"
                    # Xóa token khỏi Redis
                    redis = get_sync_redis()
                    redis.delete(f"veo3:token:{email}")
                    logger.error(f"💀 Account {email} disabled: {error}")
                session.execute(
                    update(UltraAccount).where(UltraAccount.email == email).values(**values)
                )
        session.commit()


def release_rate_limit(email: str, user_id: int):
    """Giải phóng rate limit slots"""
    redis = get_sync_redis()
    acc_key = f"veo3:acc_lock:{email}"
    user_key = f"veo3:user_lock:{user_id}"
    redis.decr(acc_key)
    redis.decr(user_key)
    # Không cho âm
    if int(redis.get(acc_key) or 0) < 0:
        redis.set(acc_key, 0)
    if int(redis.get(user_key) or 0) < 0:
        redis.set(user_key, 0)


# ═══════════════════════════════════════════════════════════════════════════════
# CELERY TASK — Tạo video
# ═══════════════════════════════════════════════════════════════════════════════

@celery_app.task(bind=True, name="app.generate_video", max_retries=2)
def generate_video_task(
    self,
    job_id: int,
    user_id: int,
    prompt: str,
    aspect_ratio: str = "16:9",
    number_of_outputs: int = 1,
    video_model: str = "veo31_fast_lp",
):
    """
    Celery task: Tạo video bằng Google Flow API (pure HTTP).

    1. Chọn account healthy
    2. Gửi request generate
    3. Poll status cho đến khi xong
    4. Download video → upload R2
    5. Update DB
    """
    logger.info(f"🎬 Task started: job={job_id} prompt=\"{prompt[:50]}...\"")

    # Update DB: job đang xử lý
    update_job_db(job_id, status="pending", started_at=datetime.utcnow(), celery_task_id=self.request.id)
    publish_progress(user_id, job_id, {"type": "progress", "status": "pending", "progress_percent": 5})

    # ── Step 1: Chọn account ──
    MAX_ACCOUNT_RETRIES = 3
    account = None
    tried_emails = []

    for attempt in range(MAX_ACCOUNT_RETRIES):
        account = get_account_token(exclude_emails=tried_emails)
        if not account:
            break
        tried_emails.append(account["email"])

        # ── Step 2: Generate video ──
        try:
            body = build_generate_request(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                number_of_outputs=number_of_outputs,
                video_model=video_model,
            )

            # ── Giải reCAPTCHA trước khi gửi request ──
            recaptcha_token = None
            try:
                from app.captcha_solver import solve_recaptcha_sync
                recaptcha_token = solve_recaptcha_sync(action="generate", proxy=account.get("proxy"))
                if recaptcha_token:
                    logger.info(f"🔓 reCAPTCHA solved, token: {recaptcha_token[:30]}...")
                else:
                    logger.warning("⚠️ reCAPTCHA solve thất bại, thử gửi không có captcha token...")
            except Exception as cap_err:
                logger.warning(f"⚠️ reCAPTCHA error (non-fatal): {cap_err}")

            headers = build_auth_headers(account["token"], recaptcha_token=recaptcha_token)

            # Proxy config
            transport = None
            if account.get("proxy"):
                transport = httpx.HTTPTransport(proxy=account["proxy"])

            logger.info(f"🚀 Sending request (account={account['email']}, attempt={attempt+1})")

            # Synchronous httpx call (Celery task chạy sync)
            with httpx.Client(timeout=30, transport=transport) as client:
                resp = client.post(
                    GENERATE_URL,
                    headers=headers,
                    content=json.dumps(body),
                )

            logger.info(f"📡 Response: HTTP {resp.status_code}")

            if resp.status_code == 401 or resp.status_code == 403:
                # Token expired / banned → thử acc khác
                report_account_result(account["email"], False, f"HTTP {resp.status_code}")
                logger.warning(f"⚠️ Account {account['email']} → HTTP {resp.status_code}, trying next...")
                continue

            if resp.status_code == 429:
                # Rate limited → thử acc khác
                report_account_result(account["email"], False, "rate_limited")
                logger.warning(f"⚠️ Account {account['email']} rate limited, trying next...")
                continue

            # Parse response
            resp_data = resp.json()
            result = parse_generate_response(resp_data)

            if result["success"] and result["operations"]:
                # ✅ Thành công — operation_id nhận được
                operation_id = result["operations"][0]["name"]
                report_account_result(account["email"], True)

                update_job_db(
                    job_id,
                    status="processing",
                    operation_id=operation_id,
                    account_id=account["account_id"],
                )
                publish_progress(user_id, job_id, {
                    "type": "progress", "status": "processing", "progress_percent": 20,
                })

                # ── Step 3: Poll status ──
                _poll_video_status(
                    job_id=job_id,
                    user_id=user_id,
                    operation_id=operation_id,
                    account=account,
                )
                return  # Done!

            else:
                # API trả lỗi → thử acc khác
                error_msg = result.get("error", "Unknown API error")
                report_account_result(account["email"], False, error_msg)
                logger.error(f"❌ API error: {error_msg}")
                continue

        except httpx.TimeoutException:
            report_account_result(account["email"], False, "timeout")
            logger.error(f"⏰ Timeout account {account['email']}")
            continue
        except Exception as e:
            report_account_result(account["email"], False, str(e))
            logger.error(f"❌ Exception: {e}")
            continue

    # ── Tất cả attempts thất bại ──
    error = "Tất cả tài khoản đều thất bại"
    update_job_db(job_id, status="failed", error=error, finished_at=datetime.utcnow())
    publish_progress(user_id, job_id, {"type": "failed", "status": "failed", "error": error})

    # Hoàn tiền
    _refund_user(user_id, job_id)

    # Release rate limit
    if account:
        release_rate_limit(account["email"], user_id)

    logger.error(f"💀 Job {job_id} failed after {MAX_ACCOUNT_RETRIES} attempts")


def _poll_video_status(
    job_id: int,
    user_id: int,
    operation_id: str,
    account: dict,
):
    """
    Poll trạng thái video cho đến khi hoàn thành hoặc timeout.
    Estimate progress dựa trên thời gian đã trôi qua.
    """
    start_time = time.time()
    EXPECTED_DURATION = 120  # ~2 phút dự kiến
    MAX_POLLS = 150  # 150 × 4s = 10 phút tối đa
    consecutive_errors = 0

    for i in range(MAX_POLLS):
        time.sleep(settings.POLL_INTERVAL_SECONDS)

        # ── Estimate progress (giống Flow website) ──
        elapsed = time.time() - start_time
        ratio = min(elapsed / EXPECTED_DURATION, 1.0)

        if ratio < 0.15:
            progress = int((ratio / 0.15) * 30)     # 0-30% (fast start)
        elif ratio < 0.6:
            progress = int(30 + ((ratio - 0.15) / 0.45) * 40)  # 30-70%
        else:
            progress = int(70 + ((ratio - 0.6) / 0.4) * 25)    # 70-95%

        progress = min(progress, 95)
        publish_progress(user_id, job_id, {
            "type": "progress", "status": "processing", "progress_percent": progress,
        })

        # ── Poll API ──
        try:
            body = build_status_request(operation_id)
            headers = build_auth_headers(account["token"])

            transport = None
            if account.get("proxy"):
                transport = httpx.HTTPTransport(proxy=account["proxy"])

            with httpx.Client(timeout=15, transport=transport) as client:
                resp = client.post(STATUS_URL, headers=headers, content=json.dumps(body))

            if resp.status_code == 401:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    _fail_job(job_id, user_id, "Token expired during polling", account)
                    return
                continue

            consecutive_errors = 0
            result = parse_status_response(resp.json())

            if result["done"]:
                if result["status"] == "completed" and result["videos"]:
                    # ✅ Video hoàn thành!
                    video_url = result["videos"][0]["download_url"]
                    media_id = result["videos"][0].get("media_id", "")

                    # Push 100%
                    publish_progress(user_id, job_id, {
                        "type": "progress", "status": "completed", "progress_percent": 100,
                    })

                    # Upload lên R2 (nếu cấu hình)
                    r2_url = _upload_to_r2(job_id, user_id, video_url)

                    # Update DB
                    update_job_db(
                        job_id,
                        status="completed",
                        progress_percent=100,
                        temp_video_url=video_url,
                        r2_url=r2_url,
                        media_id=media_id,
                        finished_at=datetime.utcnow(),
                    )

                    publish_progress(user_id, job_id, {
                        "type": "completed",
                        "status": "completed",
                        "progress_percent": 100,
                        "video_url": r2_url or video_url,
                        "media_id": media_id,
                    })

                    report_account_result(account["email"], True)
                    release_rate_limit(account["email"], user_id)
                    logger.info(f"🎉 Job {job_id} completed! URL: {(r2_url or video_url)[:80]}")
                    return

                elif result["status"] == "failed":
                    _fail_job(job_id, user_id, "Video generation failed", account)
                    return

        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors >= 5:
                _fail_job(job_id, user_id, f"Network error: {e}", account)
                return
            logger.error(f"⚠️ Poll error #{consecutive_errors}: {e}")
            continue

    # Timeout
    _fail_job(job_id, user_id, "Timeout — quá 10 phút", account)


def _upload_to_r2(job_id: int, user_id: int, video_url: str) -> str | None:
    """Upload video lên R2 (sync, dùng trong Celery)"""
    try:
        from app.r2_storage import r2_storage
        if not r2_storage.is_configured:
            return None

        r2_key = f"videos/user_{user_id}/job_{job_id}.mp4"

        # Download
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            resp = client.get(video_url)
            if resp.status_code != 200:
                logger.error(f"❌ R2 download failed: HTTP {resp.status_code}")
                return None

        # Upload
        r2_storage.client.put_object(
            Bucket=settings.R2_BUCKET,
            Key=r2_key,
            Body=resp.content,
            ContentType="video/mp4",
        )

        r2_url = f"{settings.R2_PUBLIC_URL}/{r2_key}" if settings.R2_PUBLIC_URL else None
        logger.info(f"✅ R2 upload done: {r2_key}")

        update_job_db(job_id, r2_key=r2_key, r2_url=r2_url)
        return r2_url

    except Exception as e:
        logger.error(f"❌ R2 upload failed: {e}")
        return None


def _fail_job(job_id: int, user_id: int, error: str, account: dict):
    """Đánh dấu job thất bại + hoàn tiền"""
    update_job_db(job_id, status="failed", error=error, finished_at=datetime.utcnow())
    publish_progress(user_id, job_id, {"type": "failed", "status": "failed", "error": error})
    _refund_user(user_id, job_id)
    release_rate_limit(account["email"], user_id)
    logger.error(f"💀 Job {job_id} failed: {error}")


def _refund_user(user_id: int, job_id: int):
    """Hoàn tiền cho user khi job fail"""
    from sqlalchemy import create_engine, select, update
    from sqlalchemy.orm import Session
    from app.models import GenerationJob, User, BalanceHistory

    engine = create_engine(settings.sync_db_url)
    with Session(engine) as session:
        job = session.execute(
            select(GenerationJob).where(GenerationJob.id == job_id)
        ).scalar_one_or_none()

        if not job or job.cost <= 0:
            return

        user = session.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()

        if not user:
            return

        prev_balance = user.balance
        new_balance = prev_balance + job.cost

        session.execute(
            update(User).where(User.id == user_id).values(balance=new_balance)
        )

        # Ghi lịch sử hoàn tiền
        refund_record = BalanceHistory(
            user_id=user_id,
            previous_amount=prev_balance,
            changed_amount=job.cost,
            current_amount=new_balance,
            content=f"Hoàn tiền video thất bại #{job_id}",
            type="refund",
        )
        session.add(refund_record)
        session.commit()

        logger.info(f"💰 Refunded {job.cost}đ to user #{user_id} for job #{job_id}")
