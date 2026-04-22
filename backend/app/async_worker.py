"""
Async Video Worker — Chạy trực tiếp trong FastAPI (không cần Celery)
Xử lý generate video/image bằng asyncio background tasks.
"""

import asyncio
import json
import logging
import time
from datetime import datetime

import httpx
from sqlalchemy import select, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session_factory, get_redis
from app.models import GenerationJob, UltraAccount, User, BalanceHistory
from app.rate_limiter import RateLimiter

# Alias for queue dispatch
get_redis_async = get_redis
from app.veo_template import (
    GENERATE_URL, STATUS_URL,
    build_generate_request, build_status_request,
    build_auth_headers, parse_generate_response, parse_status_response,
    MODEL_PRICING,
)

logger = logging.getLogger("veo3.async_worker")


def _find_url_in_data(data, depth=0):
    """Recursively search for any URL in nested dict/list."""
    if depth > 5:
        return None
    if isinstance(data, str) and data.startswith("https://"):
        return data
    if isinstance(data, dict):
        # Priority keys
        for key in ("mediaUrl", "fileUrl", "url", "imageUrl", "downloadUrl", "download_url"):
            val = data.get(key)
            if isinstance(val, str) and val.startswith("https://"):
                return val
        # Search all values
        for val in data.values():
            result = _find_url_in_data(val, depth + 1)
            if result:
                return result
    if isinstance(data, list):
        for item in data:
            result = _find_url_in_data(item, depth + 1)
            if result:
                return result
    return None

settings = get_settings()


# ── Helpers: Deep-search NanoAI response for URLs/fields ──
URL_KEYS = ["video_url", "download_url", "url", "media_url", "downloadUrl", "videoUrl", "fifeUrl"]

def _find_url_in_data(data, depth=0) -> str:
    """Recursively search nested dicts/lists for video/download URL"""
    if depth > 5 or not data:
        return ""
    if isinstance(data, str):
        if data.startswith("http") and ("video" in data or "media" in data or "storage" in data or ".mp4" in data):
            return data
        return ""
    if isinstance(data, dict):
        # Check known URL keys first
        for key in URL_KEYS:
            val = data.get(key)
            if val and isinstance(val, str) and val.startswith("http"):
                return val
        # Recurse into values
        for val in data.values():
            found = _find_url_in_data(val, depth + 1)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = _find_url_in_data(item, depth + 1)
            if found:
                return found
    return ""


def _find_field_in_data(data, field_names: list, depth=0) -> str:
    """Recursively search for any of the given field names"""
    if depth > 5 or not data:
        return ""
    if isinstance(data, dict):
        for name in field_names:
            val = data.get(name)
            if val and isinstance(val, str):
                return val
        for val in data.values():
            found = _find_field_in_data(val, field_names, depth + 1)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = _find_field_in_data(item, field_names, depth + 1)
            if found:
                return found
    return ""


def _extract_operation_id(data: dict) -> str:
    """Extract Google operation ID from operations response data."""
    operations = data.get("operations", [])
    if not operations or not isinstance(operations, list):
        return ""
    op = operations[0]
    return (
        op.get("operation", {}).get("name") or
        op.get("operand", {}).get("name") or
        op.get("name") or
        op.get("operationName") or
        ""
    )

async def publish_progress(user_id: int, job_id: int, data: dict):
    """Push progress directly to WebSocket clients"""
    from app.ws_manager import ws_manager
    event = {"user_id": user_id, "job_id": job_id, **data}
    await ws_manager.send_to_user(user_id, event)


async def update_job(job_id: int, **kwargs):
    """Update job in DB"""
    async with async_session_factory() as session:
        stmt = sql_update(GenerationJob).where(GenerationJob.id == job_id).values(**kwargs)
        await session.execute(stmt)
        await session.commit()


async def get_account_token(exclude_emails: list[str] | None = None) -> dict | None:
    """Get healthy account with token — load balanced by usage_count (least used first)"""
    async with async_session_factory() as session:
        query = (
            select(UltraAccount)
            .where(
                UltraAccount.is_enabled == True,
                UltraAccount.status == "healthy",
                UltraAccount.bearer_token.isnot(None),
            )
            .order_by(UltraAccount.usage_count.asc(), UltraAccount.health_score.desc())
        )
        result = await session.execute(query)
        accounts = result.scalars().all()

    if not accounts:
        return None

    exclude = set(exclude_emails or [])
    candidates = [a for a in accounts if a.email not in exclude]
    if not candidates:
        candidates = accounts

    # Select account with LEAST usage (first in sorted list) — ensures even distribution
    # Round-robin within same-usage-count accounts
    redis = await get_redis()
    if len(candidates) > 1:
        min_usage = candidates[0].usage_count or 0
        same_usage = [a for a in candidates if (a.usage_count or 0) == min_usage]
        idx = int(await redis.incr("veo3:worker_rr") or 0)
        selected = same_usage[idx % len(same_usage)]
    else:
        selected = candidates[0]

    # Token from Redis cache or DB
    token = await redis.get(f"veo3:token:{selected.email}")
    if not token:
        token = selected.bearer_token

    if not token:
        return None

    logger.info(f"🎯 Selected account #{selected.id} (usage={selected.usage_count})")

    return {
        "email": selected.email,
        "token": token,
        "proxy": selected.proxy_url,
        "account_id": selected.id,
        "flow_project_url": selected.flow_project_url,
        "cookies": selected.cookies or "",
    }


async def report_account_result(email: str, success: bool, error: str = ""):
    """Update account health after result"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(UltraAccount).where(UltraAccount.email == email)
        )
        acc = result.scalar_one_or_none()
        if not acc:
            return

        if success:
            acc.usage_count += 1
            acc.fail_count = 0  # Reset fail count on success
            acc.health_score = min(100, acc.health_score + 5)
            acc.last_used_at = datetime.utcnow()
        else:
            # reCAPTCHA errors are NOT the account's fault → small penalty
            is_captcha_error = "recaptcha" in error.lower() or "captcha" in error.lower()
            is_rate_limit = "rate" in error.lower() or "429" in error
            
            if is_captcha_error:
                acc.health_score = max(50, acc.health_score - 1)  # Minimal penalty
            elif is_rate_limit:
                acc.health_score = max(30, acc.health_score - 3)
            else:
                acc.fail_count += 1
                acc.health_score = max(0, acc.health_score - 10)
            
            # Only cooldown for real auth failures, not captcha
            if acc.fail_count >= 10 and not is_captcha_error:
                acc.status = "cooldown"
                logger.warning(f"⚠️ Account {email} set to cooldown after {acc.fail_count} fails: {error}")

        await session.commit()


async def refund_user(user_id: int, job_id: int):
    """Refund credits when job fails"""
    async with async_session_factory() as session:
        job = (await session.execute(
            select(GenerationJob).where(GenerationJob.id == job_id)
        )).scalar_one_or_none()
        if not job or job.cost <= 0:
            return

        user = (await session.execute(
            select(User).where(User.id == user_id)
        )).scalar_one_or_none()
        if not user:
            return

        # Refund credits (not VND)
        try:
            prev_credits = user.credits or 0
            new_credits = prev_credits + job.cost
            user.credits = new_credits
        except Exception:
            from sqlalchemy import text as sa_text
            prev_credits = 0
            new_credits = job.cost
            await session.execute(sa_text(
                f"UPDATE users SET credits = COALESCE(credits, 0) + {job.cost} WHERE id = {user_id}"
            ))

        session.add(BalanceHistory(
            user_id=user_id,
            previous_amount=prev_credits,
            changed_amount=job.cost,
            current_amount=new_credits,
            content=f"Hoàn {job.cost} credits — job #{job_id} thất bại",
            type="refund",
        ))
        await session.commit()
        logger.info(f"💰 Refunded {job.cost} credits to user #{user_id}")


async def fail_job(job_id: int, user_id: int, error: str):
    """Mark job as failed + refund + dispatch next waiting job"""
    await update_job(job_id, status="failed", error=error, finished_at=datetime.utcnow())
    await publish_progress(user_id, job_id, {"type": "failed", "status": "failed", "error": error})
    await refund_user(user_id, job_id)
    logger.error(f"💀 Job {job_id} failed: {error}")
    # Release slot and dispatch next
    await _release_slot_and_dispatch_next(user_id)


async def complete_job(job_id: int, user_id: int):
    """Called after successful completion — dispatch next waiting job + save to R2"""
    await _release_slot_and_dispatch_next(user_id)

    # ★ Background: upload media to R2 for permanent storage
    try:
        async with async_session_factory() as session:
            job = (await session.execute(
                select(GenerationJob).where(GenerationJob.id == job_id)
            )).scalar_one_or_none()
            if job and job.temp_video_url and not job.r2_url:
                media_type = (job.params or {}).get("media_type", "video")
                temp_url = job.temp_video_url
                asyncio.create_task(
                    _save_to_r2_background(job_id, temp_url, media_type, user_id)
                )
    except Exception as e:
        logger.warning(f"⚠️ R2 background task init error: {e}")


async def _save_to_r2_background(job_id: int, source_url: str, media_type: str, user_id: int):
    """Background task: save media to R2 permanent storage"""
    try:
        from app.r2_storage import save_media_permanently
        await save_media_permanently(job_id, source_url, media_type, user_id)
    except Exception as e:
        logger.warning(f"⚠️ R2 save failed for job #{job_id}: {e}")


async def _release_slot_and_dispatch_next(user_id: int):
    """Release 1 rate limit slot + dispatch next waiting job for this user"""
    try:
        redis = await get_redis_async()
        rate_limiter = RateLimiter(redis)
        await rate_limiter.release_user_slot(user_id)

        # Find next waiting job for this user
        async with async_session_factory() as session:
            result = await session.execute(
                select(GenerationJob)
                .where(GenerationJob.user_id == user_id)
                .where(GenerationJob.status == "waiting")
                .order_by(GenerationJob.id.asc())
                .limit(1)
            )
            next_job = result.scalar_one_or_none()

            if next_job:
                # Mark as queued
                next_job.status = "queued"
                await session.commit()

                # Acquire slot
                await rate_limiter.acquire_user_slot(user_id)

                # Dispatch
                import asyncio
                params = next_job.params or {}
                media_type = params.get("media_type", "video")
                model_key = params.get("video_model", "veo31_fast_lp")
                aspect_ratio = params.get("aspect_ratio", "16:9")

                if media_type == "image":
                    asyncio.create_task(
                        process_image_job(
                            job_id=next_job.id,
                            user_id=user_id,
                            prompt=next_job.prompt,
                            aspect_ratio=aspect_ratio,
                            image_model=model_key,
                        )
                    )
                else:
                    asyncio.create_task(
                        process_video_job(
                            job_id=next_job.id,
                            user_id=user_id,
                            prompt=next_job.prompt,
                            aspect_ratio=aspect_ratio,
                            video_model=model_key,
                        )
                    )
                logger.info(f"🔄 Queue: dispatched waiting job {next_job.id} for user {user_id}")
    except Exception as e:
        logger.error(f"⚠️ Queue dispatch error: {e}")


# ═══════════════════════════════════════════════════════════════
# CLEANUP STUCK JOBS (on server startup)
# ═══════════════════════════════════════════════════════════════

async def cleanup_stuck_jobs(max_age_minutes: int = 10):
    """
    Fail jobs stuck in processing/pending/queued for more than max_age_minutes.
    Called on server startup to clean up leftovers from previous sessions.
    Also refunds credits for stuck jobs.
    """
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)

    async with async_session_factory() as session:
        result = await session.execute(
            select(GenerationJob).where(
                GenerationJob.status.in_(["processing", "pending", "queued", "waiting"]),
                GenerationJob.started_at < cutoff,
            )
        )
        stuck_jobs = result.scalars().all()

        if not stuck_jobs:
            logger.info("✅ No stuck jobs found")
            return

        for job in stuck_jobs:
            job.status = "failed"
            job.error = "Server restarted — job đã bị timeout"
            job.finished_at = datetime.utcnow()
            logger.info(f"🧹 Cleaned stuck job #{job.id} (was {job.progress_percent}%)")

            # Refund credits
            if job.cost and job.cost > 0:
                try:
                    user = (await session.execute(
                        select(User).where(User.id == job.user_id)
                    )).scalar_one_or_none()
                    if user:
                        try:
                            user.credits = (user.credits or 0) + job.cost
                        except Exception:
                            pass
                        session.add(BalanceHistory(
                            user_id=job.user_id,
                            previous_amount=0,
                            changed_amount=job.cost,
                            current_amount=0,
                            content=f"Hoàn {job.cost} credits — server restart #{job.id}",
                            type="refund",
                        ))
                        logger.info(f"💰 Refunded {job.cost} credits for stuck job #{job.id}")
                except Exception as e:
                    logger.warning(f"⚠️ Refund error for job #{job.id}: {e}")

        await session.commit()


# ═══════════════════════════════════════════════════════════════
# GOOGLE MEDIA UPLOAD — for Image-to-Video
# ═══════════════════════════════════════════════════════════════

GOOGLE_MEDIA_UPLOAD_URL = "https://aisandbox-pa.googleapis.com/upload/v1/projects/{project_id}/flowMedia"


async def _upload_image_to_google(image_url: str, token: str, project_id: str) -> str | None:
    """
    Upload image to Google's flowMedia endpoint to get a mediaId for I2V.
    
    Flow:
      1. Download image from our server URL
      2. POST raw bytes to Google's upload endpoint
      3. Extract mediaId from response
    
    Returns Google mediaId (like "CAMaJDB...") or None on failure.
    """
    if not project_id:
        logger.error("🔴 No project_id for Google media upload")
        return None

    try:
        # Step 1: Download image from our server
        async with httpx.AsyncClient(timeout=15) as client:
            img_resp = await client.get(image_url)
            if img_resp.status_code != 200:
                logger.error(f"🔴 Failed to download image from {image_url[:60]}: HTTP {img_resp.status_code}")
                return None
            image_bytes = img_resp.content
            content_type = img_resp.headers.get("content-type", "image/jpeg")

        logger.info(f"📥 Downloaded image: {len(image_bytes)} bytes, type={content_type}")

        # Step 2: Upload to Google flowMedia
        upload_url = GOOGLE_MEDIA_UPLOAD_URL.format(project_id=project_id)
        upload_url += "?alt=json&uploadType=media"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "X-Goog-Upload-Protocol": "raw",
            "Origin": "https://labs.google",
            "Referer": "https://labs.google/",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(upload_url, headers=headers, content=image_bytes)

        logger.info(f"📤 Google media upload: HTTP {resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"🔴 Google media upload failed: {resp.status_code} {resp.text[:500]}")
            return None

        # Step 3: Extract mediaId from response
        data = resp.json()
        logger.info(f"📦 Google media upload response: {json.dumps(data)[:500]}")

        # Response format: {"name": "projects/xxx/flowMedia/MEDIA_ID", "mediaId": "CAM...", ...}
        media_id = data.get("mediaId") or data.get("media_id") or ""
        if not media_id:
            # Try extracting from name field
            name = data.get("name", "")
            if name and "/" in name:
                media_id = name.split("/")[-1]
        if not media_id:
            # Try flowMedia field
            fm = data.get("flowMedia", {})
            if isinstance(fm, dict):
                media_id = fm.get("name", "").split("/")[-1] if "/" in fm.get("name", "") else fm.get("mediaId", "")

        if media_id:
            logger.info(f"✅ Google mediaId obtained: {media_id[:30]}...")
            return media_id
        else:
            logger.error(f"🔴 No mediaId in Google response: {json.dumps(data)[:500]}")
            return None

    except Exception as e:
        import traceback
        logger.error(f"🔴 Google media upload exception: {type(e).__name__}: {e}")
        logger.error(f"🔴 Traceback: {traceback.format_exc()}")
        return None


# ═══════════════════════════════════════════════════════════════
# MAIN WORKER FUNCTION
# ═══════════════════════════════════════════════════════════════

async def process_video_job(
    job_id: int,
    user_id: int,
    prompt: str,
    aspect_ratio: str = "16:9",
    video_model: str = "veo31_fast_lp",
):
    """
    Async background task: Generate video.
    Provider:
      - "nanoai": NanoAI proxy (handles captcha + calls Google)
      - "direct": Direct Google API + CapSolver captcha
    """
    logger.info(f"🎬 Job {job_id} started: \"{prompt[:50]}...\"")

    await update_job(job_id, status="pending", started_at=datetime.utcnow())
    await publish_progress(user_id, job_id, {"type": "progress", "status": "pending", "progress_percent": 1})

    provider = settings.GENERATION_PROVIDER  # "nanoai" | "direct"

    if provider == "nanoai":
        await _process_via_nanoai(job_id, user_id, prompt, aspect_ratio, video_model)
    else:
        await _process_via_direct(job_id, user_id, prompt, aspect_ratio, video_model)


async def _process_via_nanoai_v2(
    job_id: int, user_id: int, prompt: str, aspect_ratio: str, video_model: str,
):
    """Generate video via NanoAI V2 API — returns mediaId UUID compatible with V2 upscale."""
    from app.nanoai_client import get_nanoai_client
    from app.veo_template import VIDEO_MODEL_MAP, VIDEO_ASPECT_RATIO_MAP

    account = await get_account_token()
    if not account:
        await fail_job(job_id, user_id, "Không có tài khoản nào có token!")
        return

    try:
        # Extract project ID
        project_id = ""
        flow_url = account.get("flow_project_url", "") or ""
        if "/project/" in flow_url:
            project_id = flow_url.split("/project/")[-1].split("?")[0].split("/")[0]

        # Map model & aspect ratio to V2 format
        flow_model = VIDEO_MODEL_MAP.get(video_model, "veo_3_1_t2v_lite_low_priority")
        v2_model_map = {
            "veo_3_1_t2v_fast": "VEO_3_GENERATE",
            "veo_3_1_t2v_lite": "VEO_3_GENERATE",
            "veo_3_1_t2v_quality": "VEO_3_GENERATE",
            "veo_3_1_t2v_lite_low_priority": "VEO_3_GENERATE",
        }
        v2_model = v2_model_map.get(flow_model, "VEO_3_GENERATE")
        v2_ar = VIDEO_ASPECT_RATIO_MAP.get(aspect_ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE")

        logger.info(f"🚀 NanoAI V2: account={account['email']}, model={v2_model}, ar={v2_ar}")
        await update_job(job_id, status="processing", account_id=account["account_id"])
        await publish_progress(user_id, job_id, {"type": "progress", "status": "processing", "progress_percent": 2})

        # Save project_id early
        async with async_session_factory() as session:
            j = (await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
            if j:
                p = dict(j.params or {})
                if project_id:
                    p["project_id"] = project_id
                p["aspect_ratio"] = aspect_ratio
                j.params = p
                await session.commit()
                logger.info(f"💾 Saved project_id={project_id} to job {job_id}")

        nano = get_nanoai_client()
        create_result = await nano.create_video_v2(
            access_token=account["token"],
            cookie=account.get("cookies", ""),
            prompt=prompt,
            aspect_ratio=v2_ar,
            video_model=v2_model,
        )

        if "error" in create_result and not create_result.get("success"):
            error_msg = f"NanoAI V2: {str(create_result.get('error', ''))[:200]}"
            logger.error(f"🔴 V2 create error: {error_msg}")
            await report_account_result(account["email"], False, error_msg)
            # Fallback to flow proxy
            logger.info("🔄 Falling back to Flow proxy...")
            await _process_via_nanoai(job_id, user_id, prompt, aspect_ratio, video_model)
            return

        task_id = create_result.get("taskId") or create_result.get("task_id")
        if not task_id:
            logger.error(f"🔴 No taskId: {str(create_result)[:300]}")
            await _process_via_nanoai(job_id, user_id, prompt, aspect_ratio, video_model)
            return

        logger.info(f"⏳ V2 taskId: {task_id}")
        await report_account_result(account["email"], True)

        # Save task_id
        async with async_session_factory() as s:
            j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
            if j:
                p = dict(j.params or {})
                p["nano_task_id"] = task_id
                j.params = p
                await s.commit()

        # Poll V2 task status
        MAX_POLLS = 150  # 10 min
        for i in range(MAX_POLLS):
            await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
            try:
                result = await nano.get_v2_task_status(task_id)
                code = result.get("code", "")
                success = result.get("success", False)

                if not success and code == "processing":
                    progress = min(5 + i * 2, 90)
                    await update_job(job_id, progress_percent=progress, status="processing")
                    await publish_progress(user_id, job_id, {
                        "type": "progress", "status": "processing", "progress_percent": progress,
                    })
                    if i % 5 == 0:
                        logger.info(f"📊 Job {job_id}: {progress}% ({(i+1)*settings.POLL_INTERVAL_SECONDS}s)")
                    continue

                if success:
                    data = result.get("data", {}) or {}
                    media_url = ""
                    media_id = ""
                    v2_project_id = ""
                    if isinstance(data, dict):
                        media_url = data.get("mediaUrl") or data.get("url") or ""
                        media_id = data.get("mediaId") or data.get("media_id") or ""
                        v2_project_id = data.get("projectId") or data.get("project_id") or ""

                    if not media_url:
                        media_url = _find_url_in_data(result) or ""

                    if media_url:
                        final_pid = v2_project_id or project_id
                        logger.info(f"🎉 Job {job_id} V2 done! URL={media_url[:80]}, mediaId={media_id}, pid={final_pid}")
                        await update_job(
                            job_id, status="completed", progress_percent=100,
                            temp_video_url=media_url, media_id=media_id,
                            finished_at=datetime.utcnow(),
                        )
                        await publish_progress(user_id, job_id, {
                            "type": "completed", "status": "completed",
                            "progress_percent": 100, "video_url": media_url,
                            "media_id": media_id,
                        })
                        # Save mediaId + projectId for upscale
                        async with async_session_factory() as s:
                            j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                            if j:
                                p = dict(j.params or {})
                                if media_id:
                                    p["nanoai_media_id"] = media_id
                                if final_pid:
                                    p["project_id"] = final_pid
                                    p["nanoai_project_id"] = final_pid
                                j.params = p
                                await s.commit()
                        await complete_job(job_id, user_id)
                        return
                    else:
                        logger.error(f"🔴 V2 success but no URL: {str(result)[:500]}")
                        await fail_job(job_id, user_id, "Video created but no URL")
                        return

                if code in ("error", "failed", "not_found"):
                    err = result.get("message", code)
                    logger.error(f"🔴 V2 task failed: {err}")
                    await report_account_result(account["email"], False, str(err))
                    await fail_job(job_id, user_id, str(err)[:200])
                    return

            except Exception as e:
                logger.error(f"⚠️ V2 poll error: {e}")

        await fail_job(job_id, user_id, "V2 task timeout — quá 10 phút")

    except Exception as e:
        logger.error(f"❌ V2 Exception: {e}")
        await report_account_result(account["email"], False, str(e))
        await fail_job(job_id, user_id, str(e)[:200])


async def _poll_v2_task_to_completion(nano, task_id: str, job_id: int, user_id: int, project_id: str, account: dict):
    """Poll NanoAI V2 task until completion — shared by V2 video gen and I2V flows."""
    MAX_POLLS = 150  # 10 min
    for i in range(MAX_POLLS):
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)
        try:
            result = await nano.get_v2_task_status(task_id)
            code = result.get("code", "")
            success = result.get("success", False)

            if not success and code == "processing":
                progress = min(5 + i * 2, 90)
                await update_job(job_id, progress_percent=progress, status="processing")
                await publish_progress(user_id, job_id, {
                    "type": "progress", "status": "processing", "progress_percent": progress,
                })
                if i % 5 == 0:
                    logger.info(f"📊 Job {job_id}: {progress}% ({(i+1)*settings.POLL_INTERVAL_SECONDS}s)")
                continue

            if success:
                data = result.get("data", {}) or {}
                media_url = ""
                media_id = ""
                v2_project_id = ""
                if isinstance(data, dict):
                    media_url = data.get("mediaUrl") or data.get("url") or ""
                    media_id = data.get("mediaId") or data.get("media_id") or ""
                    v2_project_id = data.get("projectId") or data.get("project_id") or ""

                if not media_url:
                    media_url = _find_url_in_data(result) or ""

                if media_url:
                    final_pid = v2_project_id or project_id
                    logger.info(f"🎉 Job {job_id} V2 done! URL={media_url[:80]}, mediaId={media_id}, pid={final_pid}")
                    await update_job(
                        job_id, status="completed", progress_percent=100,
                        temp_video_url=media_url, media_id=media_id,
                        finished_at=datetime.utcnow(),
                    )
                    await publish_progress(user_id, job_id, {
                        "type": "completed", "status": "completed",
                        "progress_percent": 100, "video_url": media_url,
                        "media_id": media_id,
                    })
                    # Save mediaId + projectId for upscale
                    async with async_session_factory() as s:
                        j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                        if j:
                            p = dict(j.params or {})
                            if media_id:
                                p["nanoai_media_id"] = media_id
                            if final_pid:
                                p["project_id"] = final_pid
                                p["nanoai_project_id"] = final_pid
                            j.params = p
                            await s.commit()
                    await complete_job(job_id, user_id)
                    return
                else:
                    logger.error(f"🔴 V2 success but no URL: {str(result)[:500]}")
                    await fail_job(job_id, user_id, "Video created but no URL")
                    return

            if code in ("error", "failed", "not_found"):
                err = result.get("message", code)
                logger.error(f"🔴 V2 task failed: {err}")
                await report_account_result(account["email"], False, str(err))
                await fail_job(job_id, user_id, str(err)[:200])
                return

        except Exception as e:
            logger.error(f"⚠️ V2 poll error: {e}")

    await fail_job(job_id, user_id, "V2 task timeout — quá 10 phút")


async def _poll_v2_i2v_task(nano, task_id: str, job_id: int, user_id: int, project_id: str, account: dict) -> str:
    """Poll NanoAI V2 I2V task. Returns 'upload_error' if image upload failed (for fallback to T2V)."""
    MAX_POLLS = 15  # Quick check — I2V upload errors come fast (~2-6s)
    for i in range(MAX_POLLS):
        await asyncio.sleep(2)
        try:
            result = await nano.get_v2_task_status(task_id)
            code = result.get("code", "")
            success = result.get("success", False)

            if not success and code == "processing":
                progress = min(5 + i * 3, 40)
                await update_job(job_id, progress_percent=progress, status="processing")
                await publish_progress(user_id, job_id, {
                    "type": "progress", "status": "processing", "progress_percent": progress,
                })
                continue

            if success:
                # I2V actually worked! Complete the job
                data = result.get("data", {}) or {}
                media_url = ""
                media_id = ""
                if isinstance(data, dict):
                    media_url = data.get("mediaUrl") or data.get("url") or ""
                    media_id = data.get("mediaId") or data.get("media_id") or ""
                if not media_url:
                    media_url = _find_url_in_data(result) or ""
                if media_url:
                    logger.info(f"🎉 I2V Job {job_id} done! URL={media_url[:80]}")
                    await update_job(
                        job_id, status="completed", progress_percent=100,
                        temp_video_url=media_url, media_id=media_id,
                        finished_at=datetime.utcnow(),
                    )
                    await publish_progress(user_id, job_id, {
                        "type": "completed", "status": "completed",
                        "progress_percent": 100, "video_url": media_url, "media_id": media_id,
                    })
                    await complete_job(job_id, user_id)
                    return "ok"
                return "ok"

            if code in ("error", "failed"):
                err = result.get("message", code)
                logger.error(f"🔴 V2 I2V task failed: {err}")
                # Check if it's an upload error → return special string for fallback
                if "upload" in err.lower():
                    logger.warning(f"⚠️ I2V Upload error detected — will fallback to T2V")
                    return "upload_error"
                # Other errors — fail the job
                await fail_job(job_id, user_id, str(err)[:200])
                return "failed"

        except Exception as e:
            logger.error(f"⚠️ V2 I2V poll error: {e}")

    # Timeout — still processing after 30s, likely succeeded but slow
    # Delegate to full poll
    await _poll_v2_task_to_completion(nano, task_id, job_id, user_id, project_id, account)
    return "ok"

async def _process_via_nanoai(
    job_id: int, user_id: int, prompt: str, aspect_ratio: str, video_model: str,
):
    """
    Generate via NanoAI proxy — 2 phase approach:
      Phase 1: NanoAI create-flow → taskId → poll NanoAI task-status → Google raw response
      Phase 2: Extract operation.name from Google response → poll Google → video URL
    Supports both text-to-video and image-to-video (when start_image_id present in job params).
    """
    from app.nanoai_client import get_nanoai_client, build_nanoai_body, build_nanoai_i2v_body
    from app.veo_template import VIDEO_MODEL_MAP

    # Check if this is an image-to-video job
    start_image_id = None
    async with async_session_factory() as session:
        job_result = await session.execute(
            select(GenerationJob).where(GenerationJob.id == job_id)
        )
        job_obj = job_result.scalar_one_or_none()
        if job_obj and job_obj.params:
            start_image_id = job_obj.params.get("start_image_id")

    MAX_RETRIES = 1
    tried_emails = []

    for attempt in range(MAX_RETRIES):
        account = await get_account_token(exclude_emails=tried_emails)
        if not account:
            break
        tried_emails.append(account["email"])

        try:
            # Extract project ID (optional for NanoAI — proxy handles it)
            project_id = ""
            flow_url = account.get("flow_project_url", "") or ""
            if "/project/" in flow_url:
                project_id = flow_url.split("/project/")[-1].split("?")[0].split("/")[0]
                logger.info(f"📁 Using project ID: {project_id}")
            else:
                logger.info(f"ℹ️ Account #{account.get('account_id', '?')} has no project_id — NanoAI will use default")

            flow_model = VIDEO_MODEL_MAP.get(video_model, "veo_3_1_t2v_lite_low_priority")

            # Build body: text-to-video or image-to-video
            if start_image_id:
                # Check if start_image_id is a URL (our server) vs Google mediaId
                is_url = start_image_id.startswith("http") or start_image_id.startswith("/static/")
                if is_url:
                    # ★ URL → need to get Google mediaId for I2V
                    logger.info(f"🖼️→📤 I2V: processing reference image: {start_image_id[:60]}...")

                    # Ensure full public URL (not relative path)
                    if start_image_id.startswith("/static/"):
                        start_image_id = f"https://veo3labai.com{start_image_id}"
                        logger.info(f"📎 Converted to full URL: {start_image_id}")

                    # Attempt 1: Upload directly to Google
                    google_media_id = await _upload_image_to_google(
                        image_url=start_image_id,
                        token=account["token"],
                        project_id=project_id,
                    )
                    if google_media_id:
                        logger.info(f"✅ Google mediaId: {google_media_id[:30]}...")
                        start_image_id = google_media_id  # Now it's a Google mediaId
                    else:
                        # Attempt 2: Use NanoAI V2 with imageUrls (NanoAI handles the upload)
                        logger.warning(f"⚠️ Google direct upload failed — trying NanoAI V2 I2V...")
                        from app.veo_template import VIDEO_ASPECT_RATIO_MAP
                        v2_ar = VIDEO_ASPECT_RATIO_MAP.get(aspect_ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE")
                        nano = get_nanoai_client()
                        v2_result = await nano.create_video_v2(
                            access_token=account["token"],
                            cookie=account.get("cookies", ""),
                            prompt=prompt,
                            aspect_ratio=v2_ar,
                            video_model="VEO_3_GENERATE",
                            image_urls=[start_image_id],
                        )
                        v2_task_id = v2_result.get("taskId") or v2_result.get("task_id")
                        if v2_task_id:
                            logger.info(f"⏳ NanoAI V2 I2V taskId: {v2_task_id}")
                            await report_account_result(account["email"], True)
                            poll_result = await _poll_v2_i2v_task(nano, v2_task_id, job_id, user_id, project_id, account)
                            if poll_result == "upload_error":
                                logger.warning(f"⚠️ V2 I2V also failed — final fallback to text-to-video")
                                start_image_id = None
                            else:
                                return  # V2 handled it (success or fail)
                        else:
                            logger.warning(f"⚠️ V2 I2V no taskId — fallback to text-to-video")
                            start_image_id = None

                if start_image_id and not start_image_id.startswith("http") and not start_image_id.startswith("/static/"):
                    # Google mediaId → use flow proxy with startImage + batchAsyncGenerateVideoStartImage
                    i2v_model = "veo_3_1_i2v_s_fast_ultra"
                    body = build_nanoai_i2v_body(
                        prompt=prompt,
                        start_image_id=start_image_id,
                        aspect_ratio=aspect_ratio,
                        video_model=i2v_model,
                        project_id=project_id,
                    )
                    logger.info(f"🖼️→🎬 Image-to-Video (flow proxy): mediaId={start_image_id[:30]}..., model={i2v_model}")

            # ★ Fallback: if no start_image_id (or upload failed) → T2V body
            if not start_image_id or (start_image_id and (start_image_id.startswith("http") or start_image_id.startswith("/static/"))):
                body = build_nanoai_body(
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    video_model=flow_model,
                    project_id=project_id,
                )

            logger.info(f"🚀 NanoAI: account={account['email']}, model={flow_model}, attempt {attempt+1}")
            await update_job(job_id, status="processing", account_id=account["account_id"])
            await publish_progress(user_id, job_id, {"type": "progress", "status": "processing", "progress_percent": 2})

            # Save project_id + aspect_ratio to job params for later upscale
            async with async_session_factory() as session:
                job_result = await session.execute(
                    select(GenerationJob).where(GenerationJob.id == job_id)
                )
                job_obj = job_result.scalar_one_or_none()
                if job_obj:
                    # ★ MUST copy dict to force SQLAlchemy JSON mutation detection
                    params = dict(job_obj.params or {})
                    if project_id:
                        params["project_id"] = project_id
                    params["aspect_ratio"] = aspect_ratio
                    job_obj.params = params  # assign NEW dict → SQLAlchemy detects change
                    await session.commit()
                    logger.info(f"💾 Saved project_id={project_id} + aspect_ratio={aspect_ratio} to job {job_id} params")

            # ══════════════════════════════════════════════════════
            # Send to NanoAI → get taskId → poll NanoAI task-status
            # NanoAI handles EVERYTHING (no direct Google calls)
            # ══════════════════════════════════════════════════════
            nano = get_nanoai_client()
            # I2V uses a different Google endpoint: batchAsyncGenerateVideoStartImage
            is_i2v = start_image_id and not start_image_id.startswith("http") and not start_image_id.startswith("/static/")
            if is_i2v:
                i2v_flow_url = "https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoStartImage"
                logger.info(f"🎯 Using I2V endpoint: {i2v_flow_url}")
            else:
                i2v_flow_url = ""  # Default (batchAsyncGenerateVideoText)
            create_result = await nano.create_flow(
                flow_auth_token=account["token"],
                body_json=body,
                flow_url=i2v_flow_url,
            )

            if "error" in create_result and not create_result.get("success"):
                error_msg = f"NanoAI: {str(create_result.get('error', ''))[:200]}"
                logger.error(f"🔴 NanoAI create-flow error: {error_msg}")
                await report_account_result(account["email"], False, error_msg)
                await fail_job(job_id, user_id, error_msg)
                return

            logger.info(f"📦 NanoAI create-flow response: {json.dumps(create_result)[:500]}")

            # Get taskId
            nano_task_id = create_result.get("taskId") or create_result.get("task_id")
            if not nano_task_id:
                # Maybe direct result
                google_data = create_result.get("result", {})
                if isinstance(google_data, dict) and google_data.get("operations"):
                    # Got Google response directly — extract video data
                    logger.info("✅ NanoAI returned Google response directly")
                    op = google_data["operations"][0]
                    operation_id = op.get("operation", {}).get("name") or op.get("name")
                    if operation_id:
                        await report_account_result(account["email"], True)
                        await update_job(job_id, status="processing", operation_id=operation_id)
                        await publish_progress(user_id, job_id, {"type": "progress", "status": "processing", "progress_percent": 25})
                        await poll_video_status(job_id, user_id, operation_id, account)
                        return
                logger.error(f"🔴 No taskId in NanoAI response: {json.dumps(create_result)[:300]}")
                await fail_job(job_id, user_id, "NanoAI không trả taskId")
                return

            logger.info(f"⏳ NanoAI taskId: {nano_task_id} — polling...")
            await report_account_result(account["email"], True)
            await publish_progress(user_id, job_id, {"type": "progress", "status": "processing", "progress_percent": 1})

            # Save taskId for potential upscale lookup later
            try:
                async with async_session_factory() as s:
                    j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                    if j:
                        p = dict(j.params or {})
                        p["nano_task_id"] = nano_task_id
                        j.params = p
                        await s.commit()
            except Exception:
                pass

            # Poll NanoAI task-status until video is ready
            # NanoAI "processing" = solving recaptcha (fast, ~10-30s)
            # NanoAI "success" = recaptcha solved, Google response returned
            MAX_TASK_POLLS = 150  # 150 × 4s = 10 min max
            for poll_i in range(MAX_TASK_POLLS):
                await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)

                try:
                    task_result = await nano.get_flow_task_status(nano_task_id)
                    code = task_result.get("code", "")
                    success = task_result.get("success", False)
                    message = task_result.get("message", "")

                    # Only update progress during recaptcha solving (processing state)
                    # Skip when success — the success handler below will set correct progress
                    if not success and code == "processing":
                        progress = 1
                        if "step" in message.lower():
                            try:
                                step_num = int(message.lower().split("step")[-1].strip().split()[0])
                                # NanoAI steps go from 1 to ~25, map to 1-30%
                                progress = min(max(int(step_num * 1.2), 1), 30)
                            except (ValueError, IndexError):
                                progress = 5
                        await update_job(job_id, progress_percent=progress, status="processing")
                        await publish_progress(user_id, job_id, {
                            "type": "progress", "status": "processing", "progress_percent": progress,
                        })
                        logger.info(f"📊 Job {job_id}: {progress}% — {message}")

                    if success:
                        # Task completed — extract data
                        # ★ First: capture NanoAI-format mediaId from 'data' (needed for upscale)
                        nanoai_data = task_result.get("data", {}) or {}
                        nanoai_media_id = ""
                        nanoai_project_id = ""
                        if isinstance(nanoai_data, dict):
                            nanoai_media_id = nanoai_data.get("mediaId") or nanoai_data.get("media_id") or ""
                            nanoai_project_id = nanoai_data.get("projectId") or nanoai_data.get("project_id") or ""
                        if nanoai_media_id:
                            logger.info(f"🔑 Captured NanoAI mediaId: {nanoai_media_id}, projectId: {nanoai_project_id}")
                            # Save immediately for upscale use
                            try:
                                async with async_session_factory() as s:
                                    j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                                    if j:
                                        p = dict(j.params or {})
                                        p["nanoai_media_id"] = nanoai_media_id
                                        if nanoai_project_id:
                                            p["nanoai_project_id"] = nanoai_project_id
                                        if not p.get("project_id") and nanoai_project_id:
                                            p["project_id"] = nanoai_project_id
                                        j.params = p
                                        await s.commit()
                            except Exception as e:
                                logger.warning(f"⚠️ Failed to save NanoAI mediaId: {e}")
                        else:
                            # Log what's in data so we can find mediaId
                            logger.info(f"📋 NanoAI task_result keys: {list(task_result.keys()) if isinstance(task_result, dict) else type(task_result)}")
                            logger.info(f"📋 NanoAI data keys: {list(nanoai_data.keys()) if isinstance(nanoai_data, dict) else type(nanoai_data)}")
                            logger.info(f"📋 NanoAI data content (first 500): {str(nanoai_data)[:500]}")

                        # NanoAI returns Google response in 'result' field (NOT 'data')
                        data = task_result.get("result", {}) or task_result.get("data", {})

                        # ── Check if this is a Google operations response ──
                        if isinstance(data, dict) and data.get("operations"):
                            # Use veo_template parser for Google's format
                            parsed = parse_status_response(data)
                            logger.info(f"📦 Google status: done={parsed['done']} status={parsed['status']}")

                            if parsed["done"]:
                                if parsed["status"] == "completed":
                                    # Find video with a URL
                                    video = None
                                    media_url = ""
                                    media_id = ""
                                    for v in parsed.get("videos", []):
                                        if v.get("download_url"):
                                            video = v
                                            break
                                    if video:
                                        media_url = video["download_url"]
                                        media_id = video.get("media_id", "")
                                    else:
                                        # Try deeper extraction from raw data
                                        media_url = _find_url_in_data(data) or ""
                                        media_id = _find_field_in_data(data, ["mediaGenerationId", "primaryMediaId", "sceneId"]) or ""
                                    if not media_url:
                                        # Video marked complete but no URL yet — might need another status poll
                                        logger.warning(f"⚠️ Job {job_id}: SUCCESSFUL but no URL — polling again...")
                                        operation_id = _extract_operation_id(data)
                                        if operation_id:
                                            await update_job(job_id, operation_id=operation_id, progress_percent=90)
                                            await publish_progress(user_id, job_id, {"type": "progress", "status": "processing", "progress_percent": 90})
                                            status_body = build_status_request(operation_id)
                                            status_result = await nano.create_flow(flow_auth_token=account["token"], flow_url=STATUS_URL, body_json=status_body, is_proxy=False)
                                            st_id = status_result.get("taskId") or status_result.get("task_id")
                                            if st_id:
                                                nano_task_id = st_id
                                                continue
                                        await fail_job(job_id, user_id, "Video complete but no download URL")
                                        return
                                    logger.info(f"🎉 Job {job_id} completed! URL: {media_url[:80]}, mediaId={media_id}, projectId={project_id}")
                                    await update_job(
                                        job_id, status="completed", progress_percent=100,
                                        temp_video_url=media_url, media_id=media_id,
                                        finished_at=datetime.utcnow(),
                                    )
                                    await publish_progress(user_id, job_id, {
                                        "type": "completed", "status": "completed",
                                        "progress_percent": 100, "video_url": media_url,
                                        "media_id": media_id,
                                    })
                                    # Save project_id + media_id for upscale
                                    try:
                                        async with async_session_factory() as s:
                                            j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                                            if j:
                                                p = dict(j.params or {})
                                                if project_id:
                                                    p["project_id"] = project_id
                                                if media_id:
                                                    p["saved_media_id"] = media_id
                                                j.params = p
                                                await s.commit()
                                    except Exception:
                                        pass
                                    await complete_job(job_id, user_id)
                                    return
                                elif parsed["status"] == "failed":
                                    error = parsed.get("error", "Video generation failed")
                                    await fail_job(job_id, user_id, error)
                                    return
                            else:
                                # Still processing — use Google's actual progress
                                google_progress = parsed.get("progress_estimate", 30)
                                await update_job(job_id, progress_percent=google_progress, status="processing")
                                await publish_progress(user_id, job_id, {
                                    "type": "progress", "status": "processing", "progress_percent": google_progress,
                                })
                                logger.info(f"📊 Job {job_id}: {google_progress}% (Google status: {parsed['status']})")

                                # Send another status request through NanoAI
                                operation_id = _extract_operation_id(data)
                                if operation_id:
                                    # Save operation_id to DB for recovery if task expires
                                    await update_job(job_id, operation_id=operation_id)
                                    status_body = build_status_request(operation_id)
                                    status_result = await nano.create_flow(
                                        flow_auth_token=account["token"],
                                        flow_url=STATUS_URL,
                                        body_json=status_body,
                                        is_proxy=False,
                                    )
                                    status_task_id = status_result.get("taskId") or status_result.get("task_id")
                                    if status_task_id:
                                        nano_task_id = status_task_id
                                        logger.info(f"🔄 Video still processing — new status task: {status_task_id[:16]}")
                                continue

                        # ── NanoAI direct result (V2 format: mediaUrl) ──
                        media_url = None
                        media_id = ""

                        if isinstance(data, dict):
                            media_url = (
                                data.get("mediaUrl") or data.get("url") or
                                data.get("downloadUrl") or data.get("fileUrl") or
                                data.get("download_url") or ""
                            )
                            media_id = data.get("mediaId") or data.get("media_id") or ""

                        if not media_url:
                            inner = task_result.get("result", {})
                            if isinstance(inner, dict):
                                media_url = inner.get("mediaUrl") or inner.get("url") or inner.get("downloadUrl") or ""
                                if not media_id:
                                    media_id = inner.get("mediaId") or ""

                        if not media_url:
                            media_url = _find_url_in_data(task_result) or ""

                        if media_url:
                            # Also capture projectId from NanoAI response data (for upscale)
                            resp_project_id = ""
                            if isinstance(data, dict):
                                resp_project_id = data.get("projectId") or data.get("project_id") or ""
                            if not resp_project_id:
                                inner = task_result.get("result", {})
                                if isinstance(inner, dict):
                                    resp_project_id = inner.get("projectId") or inner.get("project_id") or ""
                            # Use response projectId if account-level is missing
                            final_project_id = project_id or resp_project_id

                            logger.info(f"🎉 Job {job_id} completed! URL: {media_url[:80]}, mediaId={media_id}, projectId={final_project_id}")
                            await update_job(
                                job_id, status="completed", progress_percent=100,
                                temp_video_url=media_url, media_id=media_id,
                                finished_at=datetime.utcnow(),
                            )
                            await publish_progress(user_id, job_id, {
                                "type": "completed", "status": "completed",
                                "progress_percent": 100, "video_url": media_url,
                                "media_id": media_id,
                            })
                            # Save project_id + media_id to job params for upscale
                            try:
                                async with async_session_factory() as s:
                                    j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                                    if j:
                                        p = dict(j.params or {})
                                        if final_project_id:
                                            p["project_id"] = final_project_id
                                        if media_id:
                                            p["saved_media_id"] = media_id
                                        j.params = p
                                        await s.commit()
                            except Exception:
                                pass
                            await complete_job(job_id, user_id)
                            return
                        else:
                            # ★ Check for 401/UNAUTHENTICATED inside result.error
                            inner_result = task_result.get("result", {}) or {}
                            if isinstance(inner_result, dict) and inner_result.get("error"):
                                err_info = inner_result["error"]
                                err_code = err_info.get("code", 0) if isinstance(err_info, dict) else 0
                                err_status = err_info.get("status", "") if isinstance(err_info, dict) else ""
                                if err_code == 401 or err_status == "UNAUTHENTICATED":
                                    logger.error(f"🔴 Token expired (401) for account #{account.get('account_id', '?')} — disabling")
                                    await report_account_result(account["email"], False, "Token 401 UNAUTHENTICATED")
                                    # Disable account to prevent future failures
                                    try:
                                        async with async_session_factory() as s:
                                            from app.models import UltraAccount
                                            acc = (await s.execute(select(UltraAccount).where(UltraAccount.email == account["email"]))).scalar_one_or_none()
                                            if acc:
                                                acc.is_active = False
                                                await s.commit()
                                                logger.info(f"🚫 Account #{account.get('account_id', '?')} disabled due to 401")
                                    except Exception as e:
                                        logger.warning(f"⚠️ Failed to disable account: {e}")
                                    await fail_job(job_id, user_id, "Token hết hạn — admin sẽ sớm cập nhật. Vui lòng thử lại sau.")
                                    return
                            logger.error(f"🔴 Task success but no URL: {json.dumps(task_result)[:500]}")
                            await fail_job(job_id, user_id, "Video created but no URL returned")
                            return

                    if code == "not_found":
                        # NanoAI task expired — FAIL immediately, no retry
                        logger.error(f"🔴 NanoAI task expired (404) — failing job")
                        await fail_job(job_id, user_id, "NanoAI task hết hạn — vui lòng thử lại")
                        return

                    if code in ("error", "failed"):
                        error_msg = task_result.get("message", code)
                        # Parse detailed error from data
                        data_err = task_result.get("data", {})
                        if isinstance(data_err, dict):
                            inner_err = data_err.get("error", {})
                            if isinstance(inner_err, dict):
                                details = inner_err.get("details", [])
                                for d in details if isinstance(details, list) else []:
                                    if isinstance(d, dict) and d.get("reason"):
                                        error_msg = d["reason"]
                                if not error_msg or error_msg == code:
                                    error_msg = inner_err.get("message", error_msg)

                        logger.error(f"🔴 Task failed: {error_msg}")

                        # ALL errors — fail immediately, no retry
                        await report_account_result(account["email"], False, error_msg)
                        await fail_job(job_id, user_id, error_msg)
                        return

                    # "processing" → keep polling

                except Exception as poll_err:
                    logger.error(f"⚠️ Poll error: {poll_err}")
            else:
                # Timeout (for-else: loop finished without break)
                await fail_job(job_id, user_id, "NanoAI task timeout — quá 10 phút")
                return
            # If we broke out of the loop (task failed), continue to next account

        except Exception as e:
            await report_account_result(account["email"], False, str(e))
            logger.error(f"❌ NanoAI Exception: {e}")
            await fail_job(job_id, user_id, str(e)[:200])
            return

    # All attempts failed
    if not account:
        await fail_job(job_id, user_id, "Không có tài khoản nào có token!")
    else:
        await fail_job(job_id, user_id, "Tất cả tài khoản đều thất bại (NanoAI)")

async def _poll_nanoai_for_google_response(nano, task_id: str) -> dict | None:
    """Poll NanoAI flow task — delegates to nano.poll_flow_task()"""
    return await nano.poll_flow_task(task_id)


def _extract_operation_id(google_data: dict) -> str | None:
    """Extract Google operation ID from Google's raw response."""
    operations = google_data.get("operations", [])
    if operations:
        op = operations[0]
        return (
            op.get("operation", {}).get("name")
            or op.get("name")
            or op.get("operationName")
        )
    return None


async def _process_via_direct(
    job_id: int, user_id: int, prompt: str, aspect_ratio: str, video_model: str,
):
    """Legacy: Direct Google API + CapSolver captcha"""
    MAX_RETRIES = 3
    tried_emails = []
    account = None

    for attempt in range(MAX_RETRIES):
        account = await get_account_token(exclude_emails=tried_emails)
        if not account:
            break
        tried_emails.append(account["email"])

        try:
            project_id = None
            flow_url = account.get("flow_project_url", "") or ""
            if "/project/" in flow_url:
                project_id = flow_url.split("/project/")[-1].split("?")[0].split("/")[0]
                logger.info(f"📁 Using project ID: {project_id}")
            
            if not project_id:
                logger.warning(f"⚠️ Account {account['email']} has no project_id — skipping")
                continue

            # ── Giải captcha TRƯỚC (bắt buộc) ──
            from app.captcha_solver import solve_recaptcha
            recaptcha_token = await solve_recaptcha(
                action="VIDEO_GENERATION",
                proxy=account.get("proxy"),
            )
            if recaptcha_token:
                logger.info(f"🔐 reCAPTCHA solved: {recaptcha_token[:30]}...")
            else:
                logger.warning("⚠️ Captcha solve failed — trying next account")
                continue

            body = build_generate_request(
                prompt=prompt, aspect_ratio=aspect_ratio,
                number_of_outputs=1, video_model=video_model,
                recaptcha_token=recaptcha_token, project_id=project_id,
            )
            headers = build_auth_headers(account["token"])

            logger.info(f"🚀 Direct: account={account['email']}, attempt {attempt+1}")
            await publish_progress(user_id, job_id, {"type": "progress", "status": "pending", "progress_percent": 10})

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(GENERATE_URL, headers=headers, content=json.dumps(body))

            logger.info(f"📡 Response: HTTP {resp.status_code}")

            if resp.status_code in (401, 403):
                await report_account_result(account["email"], False, f"HTTP {resp.status_code}")
                continue
            if resp.status_code >= 500:
                await report_account_result(account["email"], False, f"HTTP {resp.status_code}")
                continue
            if resp.status_code == 429:
                await report_account_result(account["email"], False, "rate_limited")
                continue

            resp_data = resp.json()
            result = parse_generate_response(resp_data)

            if result["success"] and result["operations"]:
                operation_id = result["operations"][0]["name"]
                await report_account_result(account["email"], True)
                await update_job(job_id, status="processing", operation_id=operation_id, account_id=account["account_id"])
                await publish_progress(user_id, job_id, {"type": "progress", "status": "processing", "progress_percent": 20})
                await poll_video_status(job_id, user_id, operation_id, account)
                return
            else:
                error_msg = result.get("error", "Unknown API error")
                await report_account_result(account["email"], False, error_msg)
                continue

        except httpx.TimeoutException:
            await report_account_result(account["email"], False, "timeout")
            continue
        except Exception as e:
            await report_account_result(account["email"], False, str(e))
            continue

    if not account:
        await fail_job(job_id, user_id, "Không có tài khoản nào có token!")
    else:
        await fail_job(job_id, user_id, "Tất cả tài khoản đều thất bại")


async def poll_video_status(
    job_id: int,
    user_id: int,
    operation_id: str,
    account: dict,
):
    """Poll video generation status until complete or timeout"""
    MAX_POLLS = 150  # 150 × 4s = 10 min max
    consecutive_errors = 0

    for i in range(MAX_POLLS):
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)

        # Poll Google API directly
        try:
            body = build_status_request(operation_id)
            headers = build_auth_headers(account["token"])

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(STATUS_URL, headers=headers, content=json.dumps(body))

            if resp.status_code == 401:
                consecutive_errors += 1
                if consecutive_errors >= 5:
                    await fail_job(job_id, user_id, "Token hết hạn — admin sẽ sớm cập nhật. Vui lòng thử lại sau.")
                    return
                continue

            resp_data = resp.json()
            consecutive_errors = 0
            result = parse_status_response(resp_data)

            # Use actual Google progress
            google_progress = result.get("progress_estimate", 30)
            await update_job(job_id, progress_percent=google_progress, status="processing")
            await publish_progress(user_id, job_id, {
                "type": "progress", "status": "processing", "progress_percent": google_progress,
            })
            logger.info(f"📊 Job {job_id}: {google_progress}% (Google: {result['status']})")

            if result["done"]:
                if result["status"] == "completed" and result["videos"]:
                    video_url = result["videos"][0]["download_url"]
                    media_id = result["videos"][0].get("media_id", "")

                    await update_job(
                        job_id,
                        status="completed",
                        progress_percent=100,
                        temp_video_url=video_url,
                        media_id=media_id,
                        finished_at=datetime.utcnow(),
                    )
                    await publish_progress(user_id, job_id, {
                        "type": "completed",
                        "status": "completed",
                        "progress_percent": 100,
                        "video_url": video_url,
                        "media_id": media_id,
                    })
                    await report_account_result(account["email"], True)
                    logger.info(f"🎉 Job {job_id} completed! media_id={media_id} URL: {video_url[:80]}")
                    if not media_id:
                        logger.warning(f"⚠️ Job {job_id} has NO media_id — upscale won't work! Raw: {json.dumps(resp_data)[:500]}")
                    # Save project_id for upscale
                    try:
                        project_id_str = ""
                        furl = account.get("flow_project_url", "") or ""
                        if "/project/" in furl:
                            project_id_str = furl.split("/project/")[-1].split("?")[0].split("/")[0]
                        if project_id_str:
                            async with async_session_factory() as s:
                                j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                                if j:
                                    p = j.params or {}
                                    p["project_id"] = project_id_str
                                    j.params = p
                                    await s.commit()
                    except Exception as e:
                        logger.warning(f"⚠️ Could not save project_id for job {job_id}: {e}")
                    await complete_job(job_id, user_id)
                    return

                elif result["status"] == "failed":
                    error_detail = result.get("error", "Unknown reason")
                    logger.error(f"🔴 Google generation failed: {error_detail}")
                    logger.error(f"🔴 Full poll result: {json.dumps(result)[:500]}")
                    await fail_job(job_id, user_id, f"Video generation failed: {error_detail}")
                    return

        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors >= 5:
                await fail_job(job_id, user_id, f"Network error: {e}")
                return
            logger.error(f"⚠️ Poll error #{consecutive_errors}: {e}")

    await fail_job(job_id, user_id, "Timeout — quá 10 phút")


# ═══════════════════════════════════════════════════════════════
# IMAGE WORKER FUNCTION
# ═══════════════════════════════════════════════════════════════

async def process_image_job(
    job_id: int,
    user_id: int,
    prompt: str,
    aspect_ratio: str = "1:1",
    image_model: str = "nano_banana_2",
):
    """
    Image worker — supports NanoAI proxy or direct Google API.
    Image models go through same batchAsyncGenerateVideoText endpoint.
    """
    from app.veo_template import (
        build_image_request, build_auth_headers, parse_image_response,
        get_image_url, is_image_model, IMAGE_MODEL_MAP,
    )

    logger.info(f"🖼️ Image Job {job_id} started: \"{prompt[:50]}...\" model={image_model}")

    await update_job(job_id, status="pending", started_at=datetime.utcnow())
    await publish_progress(user_id, job_id, {"type": "progress", "status": "pending", "progress_percent": 10})

    # NanoAI mode — use v2 Image API directly
    if settings.GENERATION_PROVIDER == "nanoai":
        from app.nanoai_client import get_nanoai_client, IMAGE_AR_MAP
        from app.veo_template import IMAGE_MODEL_MAP

        flow_model = IMAGE_MODEL_MAP.get(image_model, "NARWHAL")
        nano_ar = IMAGE_AR_MAP.get(aspect_ratio, "IMAGE_ASPECT_RATIO_SQUARE")

        # Check if this job has a reference image
        ref_image_url = None
        async with async_session_factory() as session:
            job_result = await session.execute(
                select(GenerationJob).where(GenerationJob.id == job_id)
            )
            job_obj = job_result.scalar_one_or_none()
            if job_obj and job_obj.params:
                ref_image_url = job_obj.params.get("start_image_id")

        await _process_image_via_nanoai(job_id, user_id, prompt, nano_ar, flow_model, ref_image_url=ref_image_url)
        return

    # ── Try accounts ──
    MAX_RETRIES = 3
    tried_emails = []

    for attempt in range(MAX_RETRIES):
        account = await get_account_token(exclude_emails=tried_emails)
        if not account:
            break
        tried_emails.append(account["email"])

        try:
            # Get project_id
            project_id = None
            flow_url = account.get("flow_project_url", "") or ""
            if "/project/" in flow_url:
                project_id = flow_url.split("/project/")[-1].split("?")[0].split("/")[0]
                logger.info(f"📁 Image using project ID: {project_id}")
            else:
                async with async_session_factory() as session:
                    acc_result = await session.execute(
                        select(UltraAccount).where(UltraAccount.email == account["email"])
                    )
                    acc = acc_result.scalar_one_or_none()
                    if acc and acc.flow_project_url and "/project/" in acc.flow_project_url:
                        project_id = acc.flow_project_url.split("/project/")[-1].split("?")[0].split("/")[0]

            if not project_id:
                logger.warning(f"⚠️ Account {account['email']} has no project_id — skipping")
                continue

            # ── Giải captcha TRƯỚC (bắt buộc) ──
            from app.captcha_solver import solve_recaptcha
            recaptcha_token = await solve_recaptcha(
                action="VIDEO_GENERATION",
                proxy=account.get("proxy"),
            )
            if not recaptcha_token:
                logger.warning("⚠️ Captcha solve failed — trying next account")
                continue

            # Build + Send (SAME endpoint as video!)
            body = build_image_request(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                number_of_outputs=1,
                image_model=image_model,
                project_id=project_id,
                recaptcha_token=recaptcha_token,
            )
            headers = build_auth_headers(account["token"])
            url = get_image_url(project_id)  # Returns GENERATE_URL

            logger.info(f"🚀 Image request: account={account['email']}, attempt {attempt+1}")
            await update_job(job_id, status="processing", account_id=account["account_id"])
            await publish_progress(user_id, job_id, {"type": "progress", "status": "processing", "progress_percent": 20})

            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, headers=headers, content=json.dumps(body))

            logger.info(f"📡 Image response: HTTP {resp.status_code}")

            if resp.status_code == 400:
                error_body = resp.text[:1000]
                logger.error(f"🔴 Image API 400:\n{error_body}")
                await report_account_result(account["email"], False, f"400: {error_body[:200]}")
                continue

            if resp.status_code in (401, 403):
                error_body = resp.text[:500]
                logger.error(f"🔴 Image API {resp.status_code}: {error_body}")
                await report_account_result(account["email"], False, f"HTTP {resp.status_code}")
                continue

            if resp.status_code == 429:
                await report_account_result(account["email"], False, "rate_limited")
                continue

            # ── Parse response ──
            resp_data = resp.json()
            logger.info(f"📦 Image response keys: {list(resp_data.keys())}")
            logger.info(f"📦 Image response: {json.dumps(resp_data)[:500]}")

            # Extract operation ID (same as video — async generation)
            operation_id = None
            operations = resp_data.get("operations") or resp_data.get("generatedMediaResults", [])
            if operations and isinstance(operations, list):
                op = operations[0]
                operation_id = (
                    op.get("operationName")
                    or op.get("name")
                    or op.get("operation", {}).get("name")
                )

            if not operation_id:
                operation_id = resp_data.get("operationName") or resp_data.get("name")

            if operation_id:
                logger.info(f"🔄 Image got operation_id: {operation_id} — polling...")
                await report_account_result(account["email"], True)
                await poll_video_status(
                    job_id=job_id,
                    user_id=user_id,
                    operation_id=operation_id,
                    account=account,
                )
                return

            # Maybe direct image result (generatedImages)
            result = parse_image_response(resp_data)
            if result["success"] and result["images"]:
                img = result["images"][0]
                await update_job(
                    job_id, status="completed", progress_percent=100,
                    temp_video_url=img["download_url"],
                    media_id=img.get("media_id", ""),
                    finished_at=datetime.utcnow(),
                )
                await publish_progress(user_id, job_id, {
                    "type": "completed", "status": "completed",
                    "progress_percent": 100,
                    "video_url": img["download_url"],
                    "media_type": "image",
                    "media_id": img.get("media_id", ""),
                })
                await report_account_result(account["email"], True)
                logger.info(f"🎉 Image Job {job_id} done! URL: {img['download_url'][:80]}")
                return

            error_msg = result.get("error", "Unknown response")
            logger.error(f"❌ Image: no operation_id, no images: {json.dumps(resp_data)[:300]}")
            await report_account_result(account["email"], False, error_msg)
            continue

        except httpx.TimeoutException:
            await report_account_result(account["email"], False, "timeout")
            logger.error(f"⏰ Timeout account {account['email']}")
            continue
        except Exception as e:
            await report_account_result(account["email"], False, str(e))
            logger.error(f"❌ Exception: {e}")
            continue

    # All attempts failed
    if not account:
        await fail_job(job_id, user_id, "Không có tài khoản nào có token!")
    else:
        await fail_job(job_id, user_id, "Tất cả tài khoản đều thất bại khi tạo ảnh")


# ═══════════════════════════════════════════════════════════════
# IMAGE VIA NANOAI V2
# ═══════════════════════════════════════════════════════════════

async def _process_image_via_nanoai(
    job_id: int, user_id: int, prompt: str, aspect_ratio: str, image_model: str,
    ref_image_url: str = None,
):
    """
    Image generation via NanoAI.
    - Without reference: V2 API (/api/v2/images/create)
    - With reference: Flow proxy (flowMedia:batchGenerateImages + imageInputs)
    """
    from app.nanoai_client import get_nanoai_client, build_nanoai_i2i_body

    if ref_image_url:
        logger.info(f"🖼️+🎨 Image-to-Image: url={ref_image_url[:60]}...")

    MAX_RETRIES = 5
    tried_emails = []

    for attempt in range(MAX_RETRIES):
        account = await get_account_token(exclude_emails=tried_emails)
        if not account:
            break
        tried_emails.append(account["email"])

        try:
            project_id = None
            flow_url = account.get("flow_project_url", "") or ""
            if "/project/" in flow_url:
                project_id = flow_url.split("/project/")[-1].split("?")[0].split("/")[0]

            logger.info(f"🖼️ NanoAI Image: account={account['email']}, model={image_model}, attempt {attempt+1}")
            await update_job(job_id, status="processing", account_id=account["account_id"])
            await publish_progress(user_id, job_id, {"type": "progress", "status": "processing", "progress_percent": 15})

            nano = get_nanoai_client()

            # ═══════════════════════════════════════════════════════════
            # IMAGE-TO-IMAGE (with reference) → NanoAI V2 with imageUrls
            # ═══════════════════════════════════════════════════════════
            if ref_image_url:
                # Ensure full public URL
                ref_url = ref_image_url
                if ref_url.startswith("/static/"):
                    ref_url = f"https://veo3labai.com{ref_url}"
                    logger.info(f"📎 I2I: Converted to full URL: {ref_url}")

                # ★ Primary: Use NanoAI V2 create_image with imageUrls
                # NanoAI downloads the image and handles Google upload internally
                logger.info(f"🖼️→🎨 I2I via NanoAI V2: imageUrls=[{ref_url[:60]}...]")
                result = await nano.create_image(
                    access_token=account["token"],
                    prompt=prompt,
                    aspect_ratio=aspect_ratio,
                    image_model=image_model,
                    cookie=account.get("cookies", ""),
                    image_urls=[ref_url],
                )

                if result.get("success") and result.get("taskId"):
                    task_id = result["taskId"]
                    logger.info(f"⏳ I2I V2 taskId: {task_id} — polling...")
                    await report_account_result(account["email"], True)

                    # Poll for result — poll_v2_task returns {done, status, data} or {done, status, error}
                    poll_result = await nano.poll_v2_task(task_id, max_polls=40, interval=3)
                    if poll_result and poll_result.get("status") == "completed":
                        data = poll_result.get("data", {})
                        media_url = data.get("mediaUrl") or data.get("imageUrl") or data.get("fileUrl") or data.get("url") or ""
                        if media_url:
                            await update_job(
                                job_id, status="completed", progress_percent=100,
                                temp_video_url=media_url,
                                media_id=data.get("mediaId", ""),
                                finished_at=datetime.utcnow(),
                            )
                            await publish_progress(user_id, job_id, {
                                "type": "completed", "status": "completed",
                                "progress_percent": 100,
                                "video_url": media_url,
                                "media_type": "image",
                                "media_id": data.get("mediaId", ""),
                            })
                            logger.info(f"🎉 I2I Job {job_id} done! URL: {media_url[:80]}")
                            return
                    # I2I poll failed — try next account
                    if poll_result and poll_result.get("status") == "failed":
                        err_msg = poll_result.get("error", "I2I error")
                        logger.error(f"🔴 I2I V2 task failed: {err_msg}")
                        await report_account_result(account["email"], False, str(err_msg)[:200])
                        continue
                elif result.get("error"):
                    err_msg = str(result.get("error", ""))[:200]
                    logger.error(f"🔴 I2I V2 create failed: {err_msg}")
                    await report_account_result(account["email"], False, err_msg)
                    continue

                # ★ Fallback: Try Google upload + flow proxy
                logger.warning(f"⚠️ I2I V2 failed — trying Google upload + flow proxy...")
                google_media_id = await _upload_image_to_google(
                    image_url=ref_url,
                    token=account["token"],
                    project_id=project_id or "",
                )
                if google_media_id:
                    i2i_body = build_nanoai_i2i_body(
                        prompt=prompt,
                        media_id=google_media_id,
                        aspect_ratio=aspect_ratio,
                        image_model=image_model,
                        project_id=project_id or "",
                    )
                    i2i_flow_url = f"https://aisandbox-pa.googleapis.com/v1/projects/{project_id}/flowMedia:batchGenerateImages"
                    logger.info(f"🖼️→🎨 I2I flow proxy: mediaId={google_media_id[:30]}...")

                    create_result = await nano.create_flow(
                        flow_auth_token=account["token"],
                        body_json=i2i_body,
                        flow_url=i2i_flow_url,
                    )

                    task_id = create_result.get("taskId") or create_result.get("task_id")
                    if task_id:
                        logger.info(f"⏳ I2I flow taskId: {task_id}")
                        await report_account_result(account["email"], True)
                        poll_result = await nano.poll_flow_task(task_id, max_polls=40, interval=3)
                        if poll_result:
                            from app.veo_template import parse_image_response
                            img_result = parse_image_response(poll_result)
                            if img_result["success"] and img_result["images"]:
                                img = img_result["images"][0]
                                await update_job(
                                    job_id, status="completed", progress_percent=100,
                                    temp_video_url=img["download_url"],
                                    media_id=img.get("media_id", ""),
                                    finished_at=datetime.utcnow(),
                                )
                                await publish_progress(user_id, job_id, {
                                    "type": "completed", "status": "completed",
                                    "progress_percent": 100,
                                    "video_url": img["download_url"],
                                    "media_type": "image",
                                    "media_id": img.get("media_id", ""),
                                })
                                logger.info(f"🎉 I2I (flow) Job {job_id} done!")
                                return
                    continue  # Next account

                # Both I2I methods failed — fall through to T2I
                logger.warning(f"⚠️ All I2I methods failed — falling back to text-to-image")

            # ═══════════════════════════════════════════════════════════
            # TEXT-TO-IMAGE (no reference) → NanoAI V2 API
            # ═══════════════════════════════════════════════════════════
            result = await nano.create_image(
                access_token=account["token"],
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                image_model=image_model,
                cookie=account.get("cookies", ""),
            )

            if result.get("error") and not result.get("success"):
                raw_error = str(result.get("error", ""))
                # Try to extract detailed error from data
                data_error = result.get("data", {})
                is_auth_error = False
                if isinstance(data_error, dict):
                    inner = data_error.get("error", {})
                    if isinstance(inner, dict):
                        reason = inner.get("message", "")
                        err_code = inner.get("code", 0)
                        err_status = inner.get("status", "")
                        details = inner.get("details", [])
                        for d in details if isinstance(details, list) else []:
                            if isinstance(d, dict) and d.get("reason"):
                                reason = d["reason"]
                        raw_error = reason or raw_error
                        # Detect 401 UNAUTHENTICATED
                        if err_code == 401 or err_status == "UNAUTHENTICATED" or "authentication" in raw_error.lower():
                            is_auth_error = True

                logger.error(f"🔴 NanoAI image error: {raw_error[:200]}")

                # ★ 401 UNAUTHENTICATED — disable account + retry next
                if is_auth_error:
                    logger.error(f"🔴 Token expired (401) for {account['email']} — disabling + trying next")
                    await report_account_result(account["email"], False, "Token 401 UNAUTHENTICATED")
                    try:
                        async with async_session_factory() as s:
                            acc = (await s.execute(select(UltraAccount).where(UltraAccount.email == account["email"]))).scalar_one_or_none()
                            if acc:
                                acc.is_active = False
                                await s.commit()
                                logger.info(f"🚫 Account {account['email']} disabled due to 401")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to disable account: {e}")
                    continue  # Try next account

                # IP Filter / Policy — FAIL immediately, no retry
                if "IP_FILTER" in raw_error:
                    await fail_job(job_id, user_id, "PUBLIC_ERROR_IMAGE_OUTPUT_IP_FILTER")
                    return
                if "POLICY" in raw_error or "policy" in raw_error:
                    await fail_job(job_id, user_id, "Vi phạm chính sách nội dung — POLICY_VIOLATION")
                    return

                # Rate limit — wait and retry
                if "rate" in raw_error.lower() or "limit" in raw_error.lower():
                    logger.info("⏳ NanoAI rate limit — waiting 3s before retry...")
                    await asyncio.sleep(3)
                    tried_emails.pop()  # Remove from exclusion to retry same account

                await report_account_result(account["email"], False, raw_error[:200])
                continue

            logger.info(f"📦 NanoAI image result: {json.dumps(result)[:500]}")

            # Check direct result (instant return)
            if result.get("success") and result.get("data"):
                data = result["data"]
                media_url = (
                    data.get("mediaUrl") or data.get("url") or data.get("imageUrl") or
                    data.get("fileUrl") or
                    (data.get("result", {}) or {}).get("mediaUrl") or
                    (data.get("result", {}) or {}).get("url") or
                    (data.get("result", {}) or {}).get("fileUrl") or ""
                )
                media_id = data.get("mediaId") or data.get("id") or ""
                if media_url:
                    await update_job(
                        job_id, status="completed", progress_percent=100,
                        temp_video_url=media_url, media_id=media_id,
                        finished_at=datetime.utcnow(),
                    )
                    await publish_progress(user_id, job_id, {
                        "type": "completed", "status": "completed",
                        "progress_percent": 100, "video_url": media_url, "media_id": media_id,
                    })
                    await report_account_result(account["email"], True)
                    logger.info(f"🎉 Image Job {job_id} done via NanoAI! URL: {media_url[:80]}")
                    await complete_job(job_id, user_id)
                    return

            # Async task — need to poll
            task_id = result.get("taskId") or result.get("task_id")
            if not task_id:
                logger.error(f"🔴 No taskId in NanoAI image response: {json.dumps(result)[:300]}")
                continue

            logger.info(f"⏳ NanoAI image taskId: {task_id} — polling...")
            await publish_progress(user_id, job_id, {"type": "progress", "status": "processing", "progress_percent": 25})

            # Poll v2 task status
            async def on_progress(pct, status):
                await update_job(job_id, progress_percent=pct, status=status)
                await publish_progress(user_id, job_id, {
                    "type": "progress", "status": status, "progress_percent": pct,
                })

            poll_result = await nano.poll_v2_task(task_id, on_progress=on_progress)

            if poll_result.get("status") == "completed":
                data = poll_result.get("data", {})
                logger.info(f"📦 Image poll data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                logger.info(f"📦 Image poll data: {json.dumps(data) if isinstance(data, dict) else str(data)}")

                # NanoAI can return URL in multiple locations
                media_url = (
                    data.get("mediaUrl") or data.get("url") or
                    data.get("imageUrl") or data.get("fileUrl") or
                    data.get("download_url") or data.get("downloadUrl") or
                    # Sometimes nested in result
                    (data.get("result", {}) or {}).get("mediaUrl") or
                    (data.get("result", {}) or {}).get("url") or
                    (data.get("result", {}) or {}).get("imageUrl") or
                    (data.get("result", {}) or {}).get("fileUrl") or
                    ""
                )

                # Fallback: deep search for any URL in data
                if not media_url:
                    media_url = _find_url_in_data(data)
                    if media_url:
                        logger.info(f"🔍 Found URL via deep search: {media_url[:80]}")

                # Last resort: search for any https:// URL string in raw JSON
                if not media_url and isinstance(data, dict):
                    raw = json.dumps(data)
                    import re
                    urls = re.findall(r'https?://[^\s"\\]+', raw)
                    if urls:
                        media_url = urls[0]
                        logger.info(f"🔍 Found URL via regex: {media_url[:80]}")

                media_id = data.get("mediaId") or data.get("id") or ""

                if media_url:
                    # Save project_id in params for upscale
                    existing_params = {}
                    async with async_session_factory() as s:
                        j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                        if j:
                            existing_params = j.params or {}
                    project_id_str = ""
                    furl = account.get("flow_project_url", "") or ""
                    if "/project/" in furl:
                        project_id_str = furl.split("/project/")[-1].split("?")[0].split("/")[0]
                    existing_params["project_id"] = project_id_str

                    await update_job(
                        job_id, status="completed", progress_percent=100,
                        temp_video_url=media_url, media_id=media_id,
                        finished_at=datetime.utcnow(),
                    )
                    # Update params separately
                    async with async_session_factory() as s:
                        j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                        if j:
                            p = j.params or {}
                            p["project_id"] = project_id_str
                            j.params = p
                            await s.commit()

                    await publish_progress(user_id, job_id, {
                        "type": "completed", "status": "completed",
                        "progress_percent": 100, "video_url": media_url, "media_id": media_id,
                    })
                    await report_account_result(account["email"], True)
                    logger.info(f"🎉 Image Job {job_id} done via NanoAI! media_id={media_id} URL: {media_url[:80]}")
                    await complete_job(job_id, user_id)
                    return
                else:
                    logger.error(f"🔴 NanoAI image completed but no URL: {json.dumps(data)[:500]}")
                    await fail_job(job_id, user_id, "NanoAI image: no URL in response")
                    return
            else:
                error = poll_result.get("error", "Unknown")
                # Extract detailed error from poll_result
                poll_data = poll_result.get("data", {})
                if isinstance(poll_data, dict):
                    inner_err = poll_data.get("error", {})
                    if isinstance(inner_err, dict):
                        err_code = inner_err.get("code", 0)
                        err_status = inner_err.get("status", "")
                        err_msg = inner_err.get("message", "")
                        if err_code == 401 or err_status == "UNAUTHENTICATED":
                            logger.error(f"🔴 Token expired (401) during image poll for {account['email']}")
                            await report_account_result(account["email"], False, "Token 401 UNAUTHENTICATED")
                            try:
                                async with async_session_factory() as s:
                                    acc = (await s.execute(select(UltraAccount).where(UltraAccount.email == account["email"]))).scalar_one_or_none()
                                    if acc:
                                        acc.is_active = False
                                        await s.commit()
                                        logger.info(f"🚫 Account {account['email']} disabled due to 401")
                            except Exception:
                                pass
                            error = "Token hết hạn — vui lòng thử lại"
                            continue  # Try next account
                        if err_msg:
                            error = err_msg
                await fail_job(job_id, user_id, f"NanoAI image failed: {error}")
                return

        except Exception as e:
            await report_account_result(account["email"], False, str(e))
            logger.error(f"❌ NanoAI Image Exception: {e}")
            continue

    if not account:
        await fail_job(job_id, user_id, "Không có tài khoản nào có token!")
    else:
        await fail_job(job_id, user_id, "Tất cả tài khoản đều thất bại (NanoAI Image)")

