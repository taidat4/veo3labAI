"""
Cloudflare R2 Storage — Permanent Media Storage
================================================
Khi video/ảnh tạo xong, download từ Google temp URL → upload lên R2 → lưu URL vĩnh viễn.
Google URL hết hạn sau vài giờ, R2 URL thì vĩnh viễn.

Auto-cleanup: xóa file > 30 ngày.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

import httpx

from app.config import get_settings

logger = logging.getLogger("veo3.r2")
settings = get_settings()


def _get_r2_client():
    """Get boto3 S3 client configured for Cloudflare R2."""
    try:
        import boto3
        from botocore.config import Config as BotoConfig
    except ImportError:
        logger.warning("⚠️ boto3 not installed — R2 storage disabled")
        return None

    if not settings.R2_ENDPOINT or not settings.R2_ACCESS_KEY:
        return None

    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT,
        aws_access_key_id=settings.R2_ACCESS_KEY,
        aws_secret_access_key=settings.R2_SECRET_KEY,
        config=BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 3},
        ),
        region_name="auto",
    )


async def upload_media_to_r2(
    source_url: str,
    job_id: int,
    media_type: str = "video",  # "video" | "image"
    user_id: int = 0,
) -> dict:
    """
    Download media from Google temp URL → upload to R2 → return permanent URL.
    
    Returns:
        {"success": True, "r2_key": "...", "r2_url": "https://..."}
        or {"success": False, "error": "..."}
    """
    if not settings.R2_ENDPOINT or not settings.R2_ACCESS_KEY:
        logger.warning("⚠️ R2 not configured — skipping permanent storage")
        return {"success": False, "error": "R2 not configured"}

    try:
        # Step 1: Download from Google
        logger.info(f"📥 R2: Downloading {media_type} from Google for job #{job_id}...")
        
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            resp = await client.get(source_url)
            if resp.status_code != 200:
                logger.error(f"🔴 R2: Download failed: HTTP {resp.status_code}")
                return {"success": False, "error": f"Download failed: HTTP {resp.status_code}"}
            
            content = resp.content
            content_type = resp.headers.get("content-type", "video/mp4")

        file_size = len(content)
        logger.info(f"📦 R2: Downloaded {file_size / 1024 / 1024:.1f}MB, type={content_type}")

        # Step 2: Determine file extension and key
        ext_map = {
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/gif": ".gif",
        }
        ext = ext_map.get(content_type, ".mp4" if media_type == "video" else ".png")
        
        # Key format: media/{year}/{month}/job_{id}_{uuid}.ext
        now = datetime.utcnow()
        r2_key = f"media/{now.year}/{now.month:02d}/job_{job_id}_{uuid.uuid4().hex[:8]}{ext}"

        # Step 3: Upload to R2 (sync boto3 in thread)
        def _do_upload():
            s3 = _get_r2_client()
            if not s3:
                return False
            s3.put_object(
                Bucket=settings.R2_BUCKET,
                Key=r2_key,
                Body=content,
                ContentType=content_type,
            )
            return True

        success = await asyncio.get_event_loop().run_in_executor(None, _do_upload)
        
        if not success:
            return {"success": False, "error": "R2 upload failed"}

        # Step 4: Build public URL
        if settings.R2_PUBLIC_URL:
            r2_url = f"{settings.R2_PUBLIC_URL.rstrip('/')}/{r2_key}"
        else:
            r2_url = f"{settings.R2_ENDPOINT}/{settings.R2_BUCKET}/{r2_key}"

        logger.info(f"✅ R2: Uploaded job #{job_id} → {r2_url} ({file_size / 1024 / 1024:.1f}MB)")

        return {
            "success": True,
            "r2_key": r2_key,
            "r2_url": r2_url,
        }

    except Exception as e:
        logger.error(f"🔴 R2 upload error: {type(e).__name__}: {e}")
        return {"success": False, "error": str(e)}


async def save_media_permanently(job_id: int, source_url: str, media_type: str = "video", user_id: int = 0):
    """
    Background task: download from Google temp URL → R2 → update DB.
    Called after job completes successfully.
    """
    from app.database import async_session_factory
    from app.models import GenerationJob
    from sqlalchemy import select

    if not source_url or not source_url.startswith("http"):
        return

    result = await upload_media_to_r2(source_url, job_id, media_type, user_id)
    
    if result["success"]:
        # Update DB with permanent R2 URL
        async with async_session_factory() as session:
            job = (await session.execute(
                select(GenerationJob).where(GenerationJob.id == job_id)
            )).scalar_one_or_none()
            if job:
                job.r2_key = result["r2_key"]
                job.r2_url = result["r2_url"]
                await session.commit()
                logger.info(f"💾 Job #{job_id}: permanent URL saved to DB")
    else:
        logger.warning(f"⚠️ Job #{job_id}: R2 upload failed — keeping temp URL: {result.get('error')}")


async def cleanup_old_media(max_age_days: int = 30):
    """
    Delete R2 files older than max_age_days.
    Also clears r2_key/r2_url from DB for deleted jobs.
    Called periodically or on server startup.
    """
    if not settings.R2_ENDPOINT or not settings.R2_ACCESS_KEY:
        return 0

    from app.database import async_session_factory
    from app.models import GenerationJob
    from sqlalchemy import select, and_

    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    deleted_count = 0

    try:
        # Find jobs with R2 files older than cutoff
        async with async_session_factory() as session:
            result = await session.execute(
                select(GenerationJob).where(
                    and_(
                        GenerationJob.r2_key.isnot(None),
                        GenerationJob.created_at < cutoff,
                    )
                )
            )
            old_jobs = result.scalars().all()

        if not old_jobs:
            logger.info(f"🧹 R2 cleanup: no files older than {max_age_days} days")
            return 0

        # Delete from R2
        def _do_delete(keys):
            s3 = _get_r2_client()
            if not s3:
                return 0
            count = 0
            # Delete in batches of 100
            for i in range(0, len(keys), 100):
                batch = keys[i:i+100]
                try:
                    s3.delete_objects(
                        Bucket=settings.R2_BUCKET,
                        Delete={"Objects": [{"Key": k} for k in batch]},
                    )
                    count += len(batch)
                except Exception as e:
                    logger.error(f"🔴 R2 batch delete error: {e}")
            return count

        r2_keys = [j.r2_key for j in old_jobs if j.r2_key]
        job_ids = [j.id for j in old_jobs]

        if r2_keys:
            deleted_count = await asyncio.get_event_loop().run_in_executor(
                None, _do_delete, r2_keys
            )

        # Clear R2 refs in DB
        async with async_session_factory() as session:
            for job in old_jobs:
                db_job = (await session.execute(
                    select(GenerationJob).where(GenerationJob.id == job.id)
                )).scalar_one_or_none()
                if db_job:
                    db_job.r2_key = None
                    db_job.r2_url = None
                    db_job.temp_video_url = None
            await session.commit()

        logger.info(f"🧹 R2 cleanup: deleted {deleted_count} files older than {max_age_days} days ({len(job_ids)} jobs)")

    except Exception as e:
        logger.error(f"🔴 R2 cleanup error: {e}")

    return deleted_count
