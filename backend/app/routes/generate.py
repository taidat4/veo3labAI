"""
API Routes — Generate (Tạo video/ảnh)
Hỗ trợ: single prompt, bulk prompts, queue overflow
"""

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_redis
from app.models import User, GenerationJob, JobStatus, BalanceHistory
from app.schemas import (
    GenerateRequest, BulkGenerateRequest, GenerateResponse,
    JobStatusResponse, JobListResponse, MediaModel,
)
from app.auth import get_current_user


def _resolution_label(raw: str) -> str | None:
    """Convert 'RESOLUTION_4K' → '4K' for frontend badge."""
    if not raw:
        return None
    mapping = {"RESOLUTION_1K": "1K", "RESOLUTION_2K": "2K", "RESOLUTION_4K": "4K"}
    return mapping.get(raw, raw.replace("RESOLUTION_", "") if "RESOLUTION_" in raw else None)
from app.rate_limiter import RateLimiter
from app.veo_template import MODEL_PRICING, VIDEO_MODEL_MAP, IMAGE_MODEL_MAP, is_image_model

logger = logging.getLogger("veo3.route.generate")
router = APIRouter(prefix="/api", tags=["Generate"])


async def _dispatch_image_with_delay(
    delay_s: int, job_id: int, user_id: int, prompt: str, aspect_ratio: str, model_key: str,
):
    """Dispatch image job with stagger delay to avoid NanoAI rate limit"""
    import asyncio
    if delay_s > 0:
        await asyncio.sleep(delay_s)
    from app.async_worker import process_image_job
    await process_image_job(
        job_id=job_id,
        user_id=user_id,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        image_model=model_key,
    )

async def _dispatch_video_with_delay(
    delay_s: int, job_id: int, user_id: int, prompt: str, aspect_ratio: str, model_key: str,
):
    """Dispatch video job with stagger delay to avoid NanoAI rate limit"""
    import asyncio
    if delay_s > 0:
        await asyncio.sleep(delay_s)
    from app.async_worker import process_video_job
    await process_video_job(
        job_id=job_id,
        user_id=user_id,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        video_model=model_key,
    )

async def _create_jobs(
    user: User,
    user_id: int,
    prompts: list[str],
    aspect_ratio: str,
    number_of_outputs: int,
    model_key: str,
    resolution: str,
    db: AsyncSession,
    redis,
) -> GenerateResponse:
    """Internal: Create jobs from prompt list, handle pricing + queue"""
    from app.models import SystemSetting
    rate_limiter = RateLimiter(redis)

    # ── Tính giá — đọc từ SystemSetting (admin cài đặt) ──
    is_image = is_image_model(model_key)
    cost_key = "credit_cost_image" if is_image else "credit_cost_video"
    cost_result = await db.execute(select(SystemSetting).where(SystemSetting.key == cost_key))
    cost_setting = cost_result.scalar_one_or_none()
    base_price = int(cost_setting.value) if cost_setting else 1  # Mặc định = 1 credit
    total_videos = len(prompts) * number_of_outputs
    total_cost = base_price * total_videos

    # Check số dư
    if user.balance < total_cost:
        raise HTTPException(
            status_code=400,
            detail=f"Không đủ credit. Cần {total_cost:,}đ, hiện có {user.balance:,}đ",
        )

    # ── Check rate limit — max 8 active per user ──
    user_usage = await rate_limiter.get_user_usage(user_id)
    max_active = 8
    available_slots = max(0, max_active - user_usage)

    # ── Trừ tiền ──
    prev_balance = user.balance
    new_balance = prev_balance - total_cost
    user.balance = new_balance

    # Ghi lịch sử
    history = BalanceHistory(
        user_id=user_id,
        previous_amount=prev_balance,
        changed_amount=-total_cost,
        current_amount=new_balance,
        content=f"Tạo {total_videos} {'ảnh' if is_image_model(model_key) else 'video'} — {prompts[0][:40]}...",
        type="generation",
    )
    db.add(history)

    # ── Determine media type ──
    media_type = "image" if is_image_model(model_key) else "video"

    # ── Resolve model key ──
    if is_image_model(model_key):
        flow_model_key = IMAGE_MODEL_MAP.get(model_key, "NARWHAL")
    else:
        flow_model_key = VIDEO_MODEL_MAP.get(model_key, "veo_3_1_t2v_fast")

    # ── Tạo jobs ──
    batch_id = f"batch-{int(datetime.utcnow().timestamp())}-{uuid.uuid4().hex[:6]}"
    cost_per_video = base_price
    jobs_created = []
    queued_count = 0
    active_count = 0

    for prompt in prompts:
        for i in range(number_of_outputs):
            # Determine initial status
            if active_count < available_slots:
                status = "queued"  # Will be dispatched immediately
                active_count += 1
            else:
                status = "waiting"  # Waits in queue until slot frees
                queued_count += 1

            job = GenerationJob(
                user_id=user_id,
                prompt=prompt,
                params={
                    "aspect_ratio": aspect_ratio,
                    "resolution": resolution,
                    "video_model": model_key,
                    "media_type": media_type,
                    "number_of_outputs": 1,
                },
                model_key=flow_model_key,
                batch_id=batch_id,
                status=status,
                cost=cost_per_video,
            )
            db.add(job)
            await db.flush()
            jobs_created.append(job)

    await db.commit()

    # ── Acquire rate limit slots (only for active jobs) ──
    slots_to_acquire = min(len(jobs_created), available_slots)
    for i in range(slots_to_acquire):
        await rate_limiter.acquire_user_slot(user_id)

    # ── Dispatch ONLY active jobs (not waiting) ──
    import asyncio
    from app.async_worker import process_image_job

    dispatch_index = 0
    for job in jobs_created:
        if job.status != "queued":
            continue  # Skip waiting jobs

        if media_type == "image":
            # Stagger image jobs by 5s each to avoid NanoAI rate limiting
            delay_s = dispatch_index * 5
            asyncio.create_task(
                _dispatch_image_with_delay(
                    delay_s, job.id, user_id, job.prompt, aspect_ratio, model_key,
                )
            )
            logger.info(f"🖼️ Dispatched async IMAGE job {job.id} (delay={delay_s}s)")
        else:
            # Stagger video jobs by 3s each to avoid NanoAI rate limiting
            delay_s = dispatch_index * 3
            asyncio.create_task(
                _dispatch_video_with_delay(
                    delay_s, job.id, user_id, job.prompt, aspect_ratio, model_key,
                )
            )
            logger.info(f"🎬 Dispatched async VIDEO job {job.id} (delay={delay_s}s)")
        dispatch_index += 1

    if queued_count > 0:
        logger.info(f"⏳ {queued_count} jobs waiting in queue (slots full)")

    await db.commit()

    all_ids = [j.id for j in jobs_created]
    logger.info(
        f"📥 {len(jobs_created)} jobs ({media_type}) created: batch={batch_id}"
        f" user_id={user_id} cost={total_cost}đ active={active_count} waiting={queued_count}"
    )

    return GenerateResponse(
        success=True,
        job_id=all_ids[0],
        job_ids=all_ids,
        batch_id=batch_id,
        status="queued",
        cost=total_cost,
        remaining_balance=new_balance,
        queued_count=queued_count,
        message=f"Đang xử lý {len(jobs_created)} {'ảnh' if media_type == 'image' else 'video'}..."
                + (f" ({queued_count} trong hàng chờ)" if queued_count > 0 else ""),
    )


@router.post("/generate", response_model=GenerateResponse)
async def create_generation(
    req: GenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Tạo video/ảnh mới — single prompt"""
    user_data = get_current_user(request)
    user_id = user_data["user_id"]

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="Tài khoản bị khóa")

    redis = await get_redis()
    model_key = req.video_model.value if hasattr(req.video_model, 'value') else str(req.video_model)
    aspect = req.aspect_ratio.value if hasattr(req.aspect_ratio, 'value') else str(req.aspect_ratio)

    return await _create_jobs(
        user=user,
        user_id=user_id,
        prompts=[req.prompt],
        aspect_ratio=aspect,
        number_of_outputs=req.number_of_outputs,
        model_key=model_key,
        resolution=req.resolution,
        db=db,
        redis=redis,
    )


@router.post("/generate/bulk", response_model=GenerateResponse)
async def create_bulk_generation(
    req: BulkGenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Tạo video/ảnh hàng loạt — nhiều prompt cùng settings"""
    user_data = get_current_user(request)
    user_id = user_data["user_id"]

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="Tài khoản bị khóa")

    # Filter empty prompts
    prompts = [p.strip() for p in req.prompts if p.strip()]
    if not prompts:
        raise HTTPException(status_code=400, detail="Cần ít nhất 1 prompt")
    if len(prompts) > 100:
        raise HTTPException(status_code=400, detail="Tối đa 100 prompts/lần")

    redis = await get_redis()
    model_key = req.video_model.value if hasattr(req.video_model, 'value') else str(req.video_model)
    aspect = req.aspect_ratio.value if hasattr(req.aspect_ratio, 'value') else str(req.aspect_ratio)

    return await _create_jobs(
        user=user,
        user_id=user_id,
        prompts=prompts,
        aspect_ratio=aspect,
        number_of_outputs=req.number_of_outputs,
        model_key=model_key,
        resolution=req.resolution,
        db=db,
        redis=redis,
    )


@router.get("/job/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Lấy trạng thái 1 job"""
    user_data = get_current_user(request)

    result = await db.execute(
        select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.user_id == user_data["user_id"],
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    media_type = (job.params or {}).get("media_type", "video")
    params = job.params or {}
    # Derive upscale status from params
    upscale_status = None
    upscale_url = params.get("upscale_url")
    upscale_resolution = _resolution_label(params.get("upscale_resolution", ""))
    if upscale_url:
        upscale_status = "completed"
    elif params.get("upscale_task_id"):
        upscale_status = "processing"

    return JobStatusResponse(
        id=job.id,
        status=job.status or "unknown",
        progress_percent=job.progress_percent,
        prompt=job.prompt,
        model_key=job.model_key,
        media_type=media_type,
        video_url=job.r2_url or job.temp_video_url,
        r2_url=job.r2_url,
        media_id=job.media_id,
        error=job.error,
        cost=job.cost,
        upscale_status=upscale_status,
        upscale_url=upscale_url,
        upscale_resolution=upscale_resolution,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Lấy danh sách tất cả jobs của user"""
    user_data = get_current_user(request)

    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.user_id == user_data["user_id"])
        .order_by(GenerationJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    jobs = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).where(GenerationJob.user_id == user_data["user_id"])
    )
    total = count_result.scalar()

    # Count queued jobs
    queue_result = await db.execute(
        select(func.count()).where(
            GenerationJob.user_id == user_data["user_id"],
            GenerationJob.status == "queued",
        )
    )
    queue_count = queue_result.scalar()

    def _upscale_info(j):
        p = j.params or {}
        url = p.get("upscale_url")
        res = _resolution_label(p.get("upscale_resolution", ""))
        if url:
            return "completed", url, res
        if p.get("upscale_task_id"):
            return "processing", None, res
        return None, None, None

    return JobListResponse(
        jobs=[
            JobStatusResponse(
                id=j.id,
                status=j.status or "unknown",
                progress_percent=j.progress_percent,
                prompt=j.prompt,
                model_key=j.model_key,
                media_type=(j.params or {}).get("media_type", "video"),
                video_url=j.r2_url or j.temp_video_url,
                r2_url=j.r2_url,
                media_id=j.media_id,
                error=j.error,
                cost=j.cost,
                upscale_status=_upscale_info(j)[0],
                upscale_url=_upscale_info(j)[1],
                upscale_resolution=_upscale_info(j)[2],
                created_at=j.created_at,
                started_at=j.started_at,
                finished_at=j.finished_at,
            )
            for j in jobs
        ],
        total=total or 0,
        queue_count=queue_count or 0,
    )


@router.delete("/job/{job_id}")
async def delete_job(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Xóa 1 job (chỉ nếu đã hoàn thành hoặc thất bại)"""
    user_data = get_current_user(request)

    result = await db.execute(
        select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.user_id == user_data["user_id"],
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ("queued", "pending", "processing"):
        raise HTTPException(status_code=400, detail="Không thể xóa job đang xử lý")

    await db.delete(job)
    await db.commit()
    return {"success": True}


@router.get("/models")
async def list_models():
    """Trả về danh sách tất cả models + pricing"""
    from app.veo_template import MODEL_INFO, MODEL_PRICING
    models = []
    for key, info in MODEL_INFO.items():
        models.append({
            "key": key,
            "label": info["label"],
            "type": info["type"],
            "badge": info["badge"],
            "price": MODEL_PRICING.get(key, 0),
        })
    return {"models": models}


@router.get("/queue-status")
async def get_queue_status(request: Request):
    """Trả về số slot đang dùng / max cho user hiện tại"""
    user_data = get_current_user(request)
    user_id = user_data["user_id"]

    redis = await get_redis()
    rate_limiter = RateLimiter(redis)
    usage = await rate_limiter.get_user_usage(user_id)

    # Count waiting jobs
    from app.database import async_session_factory
    async with async_session_factory() as session:
        waiting_count = (await session.execute(
            select(func.count(GenerationJob.id))
            .where(GenerationJob.user_id == user_id)
            .where(GenerationJob.status == "waiting")
        )).scalar() or 0

    return {
        "active": usage,
        "max": 8,
        "waiting": waiting_count,
    }
