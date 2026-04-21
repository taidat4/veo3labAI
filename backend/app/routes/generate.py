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

    # Check credits (safe access)
    try:
        user_credits = user.credits or 0
    except Exception:
        user_credits = 0
    if user_credits < total_cost:
        raise HTTPException(
            status_code=400,
            detail=f"Không đủ credit. Cần {total_cost} credits, hiện có {user_credits} credits",
        )

    # ── Check rate limit — max 8 active per user ──
    user_usage = await rate_limiter.get_user_usage(user_id)
    max_active = 8
    available_slots = max(0, max_active - user_usage)

    # ── Trừ credits ──
    prev_credits = user_credits
    new_credits = prev_credits - total_cost
    try:
        user.credits = new_credits
    except Exception:
        from sqlalchemy import text as sa_text
        await db.execute(sa_text(
            f"UPDATE users SET credits = COALESCE(credits, 0) - {total_cost} WHERE id = {user_id}"
        ))

    # Ghi lịch sử
    history = BalanceHistory(
        user_id=user_id,
        previous_amount=prev_credits,
        changed_amount=-total_cost,
        current_amount=new_credits,
        content=f"Tạo {total_videos} {'ảnh' if is_image_model(model_key) else 'video'} (-{total_cost} credits)",
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
        f" user_id={user_id} cost={total_cost}cr active={active_count} waiting={queued_count}"
    )

    return GenerateResponse(
        success=True,
        job_id=all_ids[0],
        job_ids=all_ids,
        batch_id=batch_id,
        status="queued",
        cost=total_cost,
        remaining_balance=new_credits,
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



@router.get("/credit-costs")
async def get_public_credit_costs(db: AsyncSession = Depends(get_db)):
    """Public: get credit costs for video/image generation."""
    from app.models import SystemSetting
    video_r = await db.execute(select(SystemSetting).where(SystemSetting.key == "credit_cost_video"))
    image_r = await db.execute(select(SystemSetting).where(SystemSetting.key == "credit_cost_image"))
    video_s = video_r.scalar_one_or_none()
    image_s = image_r.scalar_one_or_none()
    return {
        "video_credits": int(video_s.value) if video_s else 1,
        "image_credits": int(image_s.value) if image_s else 1,
    }


@router.get("/credit-rate")
async def get_credit_rate(db: AsyncSession = Depends(get_db)):
    """Public: get VND to credits exchange rate."""
    from app.models import SystemSetting
    rate_r = await db.execute(select(SystemSetting).where(SystemSetting.key == "credit_exchange_rate"))
    rate_s = rate_r.scalar_one_or_none()
    rate = int(rate_s.value) if rate_s else 100
    return {"rate": rate, "per": 1000, "min_amount": 1000}


@router.post("/buy-credits")
async def buy_credits(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Buy credits using VND balance."""
    user_data = get_current_user(request)
    user_id = user_data["user_id"]
    from app.models import User, BalanceHistory, SystemSetting

    body = await request.json()
    amount = int(body.get("amount", 0))

    if amount < 1000:
        raise HTTPException(400, "Số tiền tối thiểu là 1.000đ")

    rate_r = await db.execute(select(SystemSetting).where(SystemSetting.key == "credit_exchange_rate"))
    rate_s = rate_r.scalar_one_or_none()
    rate = int(rate_s.value) if rate_s else 100

    credits_to_add = int(amount / 1000 * rate)
    if credits_to_add <= 0:
        raise HTTPException(400, "Số tiền quá nhỏ")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()

    if user.balance < amount:
        raise HTTPException(400, f"Số dư không đủ. Cần {amount:,}đ, hiện có {user.balance:,}đ")

    prev_balance = user.balance
    user.balance -= amount

    try:
        old_credits = user.credits or 0
        user.credits = old_credits + credits_to_add
    except Exception:
        from sqlalchemy import text as sa_text
        old_credits = 0
        await db.execute(sa_text(
            f"UPDATE users SET credits = COALESCE(credits, 0) + {credits_to_add} WHERE id = {user_id}"
        ))

    db.add(BalanceHistory(
        user_id=user_id,
        previous_amount=prev_balance,
        changed_amount=-amount,
        current_amount=user.balance,
        content=f"Mua {credits_to_add:,} credits ({amount:,}đ)",
        type="credit_purchase",
    ))

    await db.commit()
    await db.refresh(user)
    new_credits = getattr(user, 'credits', 0) or 0

    return {
        "success": True,
        "message": f"Đã mua {credits_to_add:,} credits!",
        "credits_added": credits_to_add,
        "new_balance": user.balance,
        "new_credits": new_credits,
    }


@router.get("/plans")
async def list_public_plans(request: Request, db: AsyncSession = Depends(get_db)):
    """Public: list active subscription plans for pricing page."""
    from app.models import SubscriptionPlan, BalanceHistory

    # Check if user already used trial (optional auth)
    trial_used = False
    try:
        user_data = get_current_user(request)
        uid = user_data["user_id"]
        trial_check = await db.execute(
            select(func.count(BalanceHistory.id))
            .where(BalanceHistory.user_id == uid)
            .where(BalanceHistory.type == "plan_purchase")
            .where(BalanceHistory.content.like("%Dùng Thử%"))
        )
        trial_used = (trial_check.scalar() or 0) > 0
    except Exception:
        pass  # Not logged in — show trial

    result = await db.execute(
        select(SubscriptionPlan)
        .where(SubscriptionPlan.is_active == True)
        .order_by(SubscriptionPlan.sort_order)
    )
    plans = result.scalars().all()
    return {
        "trial_used": trial_used,
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "credits": p.credits,
                "price": p.price,
                "duration_days": p.duration_days,
                "features": p.features if isinstance(p.features, list) else (
                    __import__("json").loads(p.features) if isinstance(p.features, str) else []
                ),
            }
            for p in plans
        ]
    }


@router.post("/purchase-plan")
async def purchase_plan(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Purchase a subscription plan or credit pack."""
    user_data = get_current_user(request)
    user_id = user_data["user_id"]
    from app.models import SubscriptionPlan, User, BalanceHistory
    from datetime import timedelta

    body = await request.json()
    plan_id = body.get("plan_id")
    if not plan_id:
        raise HTTPException(400, "plan_id is required")

    plan = (await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id)
    )).scalar_one_or_none()
    if not plan or not plan.is_active:
        raise HTTPException(404, "Gói không tồn tại")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()

    # Trial: only once per account
    if plan.price == 0:
        existing = (await db.execute(
            select(func.count(BalanceHistory.id))
            .where(BalanceHistory.user_id == user_id)
            .where(BalanceHistory.type == "plan_purchase")
            .where(BalanceHistory.content.like(f"%{plan.name}%"))
        )).scalar() or 0
        if existing > 0:
            raise HTTPException(400, "Bạn đã sử dụng gói Dùng thử rồi!")

    if plan.price > 0 and user.balance < plan.price:
        raise HTTPException(400, f"Số dư không đủ. Cần {plan.price:,}đ, hiện có {user.balance:,}đ")

    prev_balance = user.balance
    if plan.price > 0:
        user.balance -= plan.price

    # Add credits to user (safe for missing column)
    try:
        old_credits = user.credits or 0
        user.credits = old_credits + plan.credits
    except Exception:
        # Column may not exist yet — use raw SQL
        from sqlalchemy import text
        try:
            await db.execute(text(
                f"UPDATE users SET credits = COALESCE(credits, 0) + {plan.credits} WHERE id = {user_id}"
            ))
        except Exception:
            pass  # Column truly doesn't exist, skip

    if plan.duration_days > 0:
        user.plan_id = plan.id
        user.plan_expires_at = datetime.utcnow() + timedelta(days=plan.duration_days)

    db.add(BalanceHistory(
        user_id=user_id,
        previous_amount=prev_balance,
        changed_amount=-plan.price,
        current_amount=user.balance,
        content=f"Mua gói: {plan.name} (+{plan.credits} credits)",
        type="plan_purchase",
    ))

    await db.commit()
    await db.refresh(user)
    new_credits = getattr(user, 'credits', 0) or 0
    logger.info(f"[PLAN] User {user_id} purchased '{plan.name}' for {plan.price}đ, +{plan.credits} credits")

    return {
        "success": True,
        "message": f"Đã mua gói {plan.name} thành công! +{plan.credits} credits",
        "new_balance": user.balance,
        "new_credits": new_credits,
        "plan_name": plan.name,
        "credits": plan.credits,
        "expires_at": user.plan_expires_at.isoformat() if user.plan_expires_at else None,
    }

