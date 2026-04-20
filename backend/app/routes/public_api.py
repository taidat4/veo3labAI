"""
Public API v1 — Cho users kết nối từ app/web bên ngoài
Auth: API Key trong header `X-API-Key: uf_xxx`
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, GenerationJob
from app.schemas import GenerateRequest, JobStatusResponse

logger = logging.getLogger("veo3.api.public")
router = APIRouter(prefix="/api/v1", tags=["Public API"])


async def get_api_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Auth bằng API Key"""
    api_key = request.headers.get("X-API-Key", "")
    if not api_key or not (api_key.startswith("veo3_") or api_key.startswith("uf_")):
        raise HTTPException(status_code=401, detail="Missing or invalid API key. Use header: X-API-Key: veo3_xxx")

    result = await db.execute(select(User).where(User.api_key == api_key))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key")
    if user.is_banned:
        raise HTTPException(status_code=403, detail="Account suspended")
    return user


@router.get("/me")
async def api_me(request: Request, db: AsyncSession = Depends(get_db)):
    """Thông tin user qua API key"""
    user = await get_api_user(request, db)
    return {
        "user_id": user.id,
        "username": user.username,
        "balance": user.balance,
        "role": user.role,
        "plan_id": user.plan_id,
        "plan_expires_at": user.plan_expires_at.isoformat() if user.plan_expires_at else None,
    }


@router.post("/generate")
async def api_generate(
    req: GenerateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Tạo video/ảnh qua API — same logic as web"""
    user = await get_api_user(request, db)

    from app.veo_template import MODEL_PRICING, is_image_model
    from app.rate_limiter import RateLimiter
    from app.database import get_redis

    redis = await get_redis()
    rate_limiter = RateLimiter(redis)

    model_key = req.video_model.value if hasattr(req.video_model, 'value') else str(req.video_model)
    aspect = req.aspect_ratio.value if hasattr(req.aspect_ratio, 'value') else str(req.aspect_ratio)

    # Price check
    base_price = MODEL_PRICING.get(model_key, 5000)
    total_cost = base_price * req.number_of_outputs
    if user.balance < total_cost:
        raise HTTPException(status_code=400, detail=f"Insufficient credits. Need {total_cost}, have {user.balance}")

    # Rate limit
    usage = await rate_limiter.get_user_usage(user.id)
    if usage >= 8:
        raise HTTPException(status_code=429, detail="Max concurrent jobs reached (8). Wait for current jobs to finish.")

    # Delegate to main generate logic
    from app.routes.generate import _create_jobs
    result = await _create_jobs(
        user=user,
        user_id=user.id,
        prompts=[req.prompt],
        aspect_ratio=aspect,
        number_of_outputs=req.number_of_outputs,
        model_key=model_key,
        resolution=req.resolution,
        db=db,
        redis=redis,
    )

    return {
        "success": True,
        "job_id": result.job_id,
        "job_ids": result.job_ids,
        "cost": result.cost,
        "remaining_balance": result.remaining_balance,
        "message": result.message,
    }


@router.get("/jobs")
async def api_list_jobs(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Danh sách jobs của user"""
    user = await get_api_user(request, db)

    result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.user_id == user.id)
        .order_by(GenerationJob.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
    )
    jobs = result.scalars().all()

    total = (await db.execute(
        select(func.count()).where(GenerationJob.user_id == user.id)
    )).scalar() or 0

    def _upscale_info(j):
        p = j.params or {}
        url = p.get("upscale_url")
        if url:
            return "completed", url
        if p.get("upscale_task_id"):
            return "processing", None
        return None, None

    return {
        "jobs": [
            {
                "id": j.id,
                "status": j.status,
                "prompt": j.prompt,
                "media_type": (j.params or {}).get("media_type", "video"),
                "video_url": j.r2_url or j.temp_video_url,
                "upscale_status": _upscale_info(j)[0],
                "upscale_url": _upscale_info(j)[1],
                "cost": j.cost,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            }
            for j in jobs
        ],
        "total": total,
    }


@router.get("/jobs/{job_id}")
async def api_job_status(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Chi tiết 1 job"""
    user = await get_api_user(request, db)

    result = await db.execute(
        select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    params = job.params or {}
    upscale_url = params.get("upscale_url")
    upscale_status = None
    if upscale_url:
        upscale_status = "completed"
    elif params.get("upscale_task_id"):
        upscale_status = "processing"

    return {
        "id": job.id,
        "status": job.status,
        "prompt": job.prompt,
        "media_type": params.get("media_type", "video"),
        "video_url": job.r2_url or job.temp_video_url,
        "upscale_status": upscale_status,
        "upscale_url": upscale_url,
        "cost": job.cost,
        "error": job.error,
        "progress_percent": job.progress_percent,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
