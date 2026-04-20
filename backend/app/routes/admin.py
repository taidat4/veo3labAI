"""
API Routes — Admin (Quản lý accounts, tokens, pool, users, settings, logs)
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, update, delete, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, get_redis
from app.models import (
    UltraAccount, AccountStatus, User, GenerationJob,
    BalanceHistory, SystemSetting, UserRateLimit, SubscriptionPlan,
)
from app.schemas import (
    AddAccountRequest, UpdateTokenRequest,
    AccountStatusResponse, PoolStatsResponse,
)
from app.auth import require_admin, verify_admin_secret, create_admin_token
from app.session_manager import SessionManager

logger = logging.getLogger("veo3.route.admin")
router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN AUTH (Secret Key — tách biệt hoàn toàn khỏi user auth)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/auth")
async def admin_auth(request: Request):
    """
    Xác thực admin bằng secret key.
    Body: { "secret_key": "..." }
    Returns: admin JWT token (signed bằng ADMIN_SECRET_KEY, KHÔNG phải JWT_SECRET)
    """
    body = await request.json()
    secret_key = body.get("secret_key", "")

    if not secret_key:
        raise HTTPException(status_code=400, detail="Secret key is required")

    if not verify_admin_secret(secret_key):
        raise HTTPException(status_code=403, detail="Invalid secret key")

    token = create_admin_token(secret_key)
    return {
        "success": True,
        "admin_token": token,
        "message": "Admin access granted",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/dashboard")
async def get_dashboard_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Tổng quan hệ thống cho admin dashboard"""
    require_admin(request)

    # Total users
    total_users = (await db.execute(func.count(User.id))).scalar() or 0

    # Total jobs
    total_jobs = (await db.execute(func.count(GenerationJob.id))).scalar() or 0

    # Completed jobs
    completed_jobs = (await db.execute(
        select(func.count(GenerationJob.id)).where(GenerationJob.status == "completed")
    )).scalar() or 0

    # Failed jobs
    failed_jobs = (await db.execute(
        select(func.count(GenerationJob.id)).where(GenerationJob.status == "failed")
    )).scalar() or 0

    # Processing jobs (active right now)
    active_jobs = (await db.execute(
        select(func.count(GenerationJob.id)).where(
            GenerationJob.status.in_(["queued", "pending", "processing"])
        )
    )).scalar() or 0

    # Total revenue (sum of all completed job costs)
    total_revenue = (await db.execute(
        select(func.sum(GenerationJob.cost)).where(GenerationJob.status == "completed")
    )).scalar() or 0

    # Total accounts
    total_accounts = (await db.execute(func.count(UltraAccount.id))).scalar() or 0
    healthy_accounts = (await db.execute(
        select(func.count(UltraAccount.id)).where(UltraAccount.status == "healthy")
    )).scalar() or 0

    # OmoCaptcha balance
    captcha_balance = None
    try:
        from app.captcha_solver import get_captcha_balance
        captcha_balance = await get_captcha_balance()
    except Exception:
        pass

    # Recent jobs (last 5)
    recent_jobs_result = await db.execute(
        select(GenerationJob)
        .order_by(desc(GenerationJob.created_at))
        .limit(5)
    )
    recent_jobs = [
        {
            "id": j.id,
            "prompt": j.prompt[:60] + "..." if len(j.prompt) > 60 else j.prompt,
            "status": j.status,
            "cost": j.cost,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in recent_jobs_result.scalars().all()
    ]

    return {
        "total_users": total_users,
        "total_jobs": total_jobs,
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "active_jobs": active_jobs,
        "total_revenue": total_revenue,
        "total_accounts": total_accounts,
        "healthy_accounts": healthy_accounts,
        "captcha_balance": captcha_balance,
        "recent_jobs": recent_jobs,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ACCOUNTS POOL (giữ nguyên logic cũ)
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/pool", response_model=PoolStatsResponse)
async def get_pool_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Xem tổng quan pool accounts"""
    require_admin(request)

    redis = await get_redis()
    session_mgr = SessionManager(redis)
    stats = await session_mgr.get_pool_stats()

    return PoolStatsResponse(
        total_accounts=stats["total_accounts"],
        healthy_accounts=stats["healthy_accounts"],
        total_capacity=stats["total_accounts"] * 40,
        total_used=sum(a.get("current_concurrent", 0) for a in stats["accounts"]),
        available=stats["healthy_accounts"] * 40 - sum(a.get("current_concurrent", 0) for a in stats["accounts"]),
        avg_health=stats["avg_health"],
        accounts=[
            AccountStatusResponse(
                id=a["id"],
                email=a["email"],
                status=a["status"],
                is_enabled=a.get("is_enabled", True),
                health_score=a["health_score"],
                usage_count=a["usage_count"],
                current_concurrent=a["current_concurrent"],
                max_concurrent=a["max_concurrent"],
                has_token=a["has_token"],
                bearer_token=a.get("bearer_token"),
                token_expires_at=a.get("token_expires_at"),
                last_used_at=a.get("last_used_at"),
                last_refresh_at=a.get("last_refresh_at"),
                proxy_url=a.get("proxy_url"),
                flow_project_url=a.get("flow_project_url"),
                cookies=a.get("cookies"),
            )
            for a in stats["accounts"]
        ],
    )


@router.post("/accounts")
async def add_account(
    req: AddAccountRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Thêm tài khoản Ultra mới"""
    require_admin(request)

    result = await db.execute(
        select(UltraAccount).where(UltraAccount.email == req.email)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email đã tồn tại")

    account = UltraAccount(
        email=req.email,
        password=req.password,
        totp_secret=req.totp_secret,
        proxy_url=req.proxy_url,
        flow_project_url=req.flow_project_url,
        bearer_token=req.bearer_token,
        status="healthy" if req.bearer_token else "expired",
    )
    db.add(account)
    await db.commit()

    if req.bearer_token:
        redis = await get_redis()
        session_mgr = SessionManager(redis)
        await session_mgr.store_token(req.email, req.bearer_token)

    logger.info(f"✅ Account added: {req.email}")
    return {"success": True, "message": f"Đã thêm {req.email}"}


@router.put("/accounts/{account_id}/token")
async def update_token(
    account_id: int,
    req: UpdateTokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Cập nhật Bearer Token thủ công cho 1 account"""
    require_admin(request)

    result = await db.execute(
        select(UltraAccount).where(UltraAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    redis = await get_redis()
    session_mgr = SessionManager(redis)
    await session_mgr.store_token(
        account.email,
        req.bearer_token,
        expires_in_minutes=req.expires_in_minutes,
        source="manual",
    )

    logger.info(f"🔑 Token updated: {account.email} (expires in {req.expires_in_minutes} min)")
    return {
        "success": True,
        "message": f"Token đã cập nhật cho {account.email}",
        "expires_in_minutes": req.expires_in_minutes,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NANO_EXT — Extension webhook nhận token tự động
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/nano-ext/push-token")
async def nano_ext_push_token(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint cho nano_ext Chrome extension push token.
    Body: { "email": "xxx@gmail.com", "token": "ya29...", "expires_in_minutes": 55 }
    Không cần admin auth — dùng NANOAI_API_KEY để xác thực.
    """
    body = await request.json()
    email = body.get("email", "").strip()
    token = body.get("token", "").strip()
    expires = body.get("expires_in_minutes", 180)

    # Auth by NanoAI key or admin token
    auth_header = request.headers.get("authorization", "")
    from app.config import get_settings
    s = get_settings()

    is_authorized = False
    if auth_header.startswith("Bearer "):
        key = auth_header[7:]
        if key == s.NANOAI_API_KEY or key == s.ADMIN_SECRET_KEY:
            is_authorized = True

    # Also accept admin JWT
    if not is_authorized:
        try:
            require_admin(request)
            is_authorized = True
        except Exception:
            pass

    if not is_authorized:
        raise HTTPException(status_code=403, detail="Unauthorized")

    if not email or not token:
        raise HTTPException(status_code=400, detail="email and token required")

    # Find account by email
    result = await db.execute(
        select(UltraAccount).where(UltraAccount.email == email)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail=f"Account {email} not found")

    # Store token
    redis = await get_redis()
    session_mgr = SessionManager(redis)
    await session_mgr.store_token(
        email, token,
        expires_in_minutes=expires,
        source="nano_ext",
    )

    logger.info(f"🔌 NanoExt token pushed: {email} (expires in {expires} min)")
    return {
        "success": True,
        "message": f"Token saved for {email}",
        "expires_in_minutes": expires,
    }


@router.get("/nano-ext/config")
async def get_nano_ext_config(request: Request, db: AsyncSession = Depends(get_db)):
    """Admin lấy cấu hình nano_ext"""
    require_admin(request)

    # Get settings from DB or defaults
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "nano_ext_interval")
    )
    interval_setting = result.scalar_one_or_none()
    interval = int(interval_setting.value) if interval_setting else 35

    result2 = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "nano_ext_enabled")
    )
    enabled_setting = result2.scalar_one_or_none()
    enabled = enabled_setting.value == "true" if enabled_setting else True

    from app.config import get_settings
    s = get_settings()

    return {
        "enabled": enabled,
        "interval_minutes": interval,
        "webhook_url": f"{request.base_url}api/admin/nano-ext/push-token",
        "api_key": s.NANOAI_API_KEY[:8] + "..." if s.NANOAI_API_KEY else "",
    }


@router.put("/nano-ext/config")
async def update_nano_ext_config(request: Request, db: AsyncSession = Depends(get_db)):
    """Admin cập nhật cấu hình nano_ext"""
    require_admin(request)
    body = await request.json()

    if "interval_minutes" in body:
        val = str(body["interval_minutes"])
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == "nano_ext_interval")
        )
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = val
        else:
            db.add(SystemSetting(key="nano_ext_interval", value=val))

    if "enabled" in body:
        val = "true" if body["enabled"] else "false"
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == "nano_ext_enabled")
        )
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = val
        else:
            db.add(SystemSetting(key="nano_ext_enabled", value=val))

    await db.commit()
    logger.info(f"⚙️ NanoExt config updated: {body}")
    return {"success": True, "message": "Config updated"}


@router.put("/accounts/{account_id}")
async def update_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Cập nhật thông tin account (password, totp_secret, proxy, flow_project_url)"""
    require_admin(request)

    body = await request.json()

    result = await db.execute(
        select(UltraAccount).where(UltraAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Update allowed fields
    updatable = ["password", "totp_secret", "proxy_url", "flow_project_url", "cookies"]
    changed = []
    for field in updatable:
        if field in body:
            setattr(account, field, body[field] or None)
            changed.append(field)

    if changed:
        account.updated_at = datetime.utcnow()
        await db.commit()
        logger.info(f"✏️ Account {account.email} updated: {', '.join(changed)}")

    return {
        "success": True,
        "message": f"Đã cập nhật {', '.join(changed)} cho {account.email}",
        "changed": changed,
    }


@router.put("/accounts/{account_id}/toggle")
async def toggle_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Bật/Tắt account — khi tắt, account bị bỏ qua hoàn toàn"""
    require_admin(request)

    result = await db.execute(
        select(UltraAccount).where(UltraAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    new_state = not account.is_enabled
    account.is_enabled = new_state
    account.updated_at = datetime.utcnow()
    await db.commit()

    state_text = "BẬT" if new_state else "TẮT"
    logger.info(f"🔀 Account {account.email} toggled: {state_text}")
    return {
        "success": True,
        "is_enabled": new_state,
        "message": f"Account {account.email} đã {state_text}",
    }

@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Xóa tài khoản Ultra"""
    require_admin(request)

    result = await db.execute(
        select(UltraAccount).where(UltraAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    redis = await get_redis()
    await redis.delete(f"veo3:token:{account.email}")
    await redis.delete(f"veo3:token_exp:{account.email}")

    await db.execute(
        delete(UltraAccount).where(UltraAccount.id == account_id)
    )
    await db.commit()

    logger.info(f"🗑️ Account deleted: {account.email}")
    return {"success": True}


@router.get("/accounts/{account_id}/details")
async def get_account_details(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Lấy full details account (bao gồm password + totp_secret).
    Dùng bởi Token Extractor tool để auto-login Google.
    """
    require_admin(request)

    result = await db.execute(
        select(UltraAccount).where(UltraAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return {
        "id": account.id,
        "email": account.email,
        "password": account.password,
        "totp_secret": account.totp_secret,
        "proxy_url": account.proxy_url,
        "flow_project_url": account.flow_project_url,
        "status": account.status,
        "has_token": bool(account.bearer_token),
        "token_expires_at": account.token_expires_at.isoformat() if account.token_expires_at else None,
    }


@router.post("/accounts/{account_id}/extract-token")
async def extract_token(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger auto token extraction cho 1 account.
    Chạy Playwright login + capture bearer token.
    """
    require_admin(request)

    result = await db.execute(
        select(UltraAccount).where(UltraAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if not account.totp_secret:
        raise HTTPException(status_code=400, detail=f"Account {account.email} chưa có TOTP secret! Vào Thêm Account hoặc sửa account để thêm TOTP key.")

    import subprocess
    import os
    import sys

    tool_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "tools", "token_extractor", "main.py"
    )

    if not os.path.exists(tool_path):
        raise HTTPException(status_code=500, detail=f"Token extractor not found: {tool_path}")

    logger.info(f"🚀 Starting token extraction for {account.email} (ID: {account_id})")

    # Spawn in a NEW VISIBLE CONSOLE WINDOW so user can see the browser
    try:
        if sys.platform == "win32":
            # Windows: open new CMD window that stays open
            cmd = f'start "Token Extractor - {account.email}" cmd /c python "{tool_path}" --account-id {account_id}'
            subprocess.Popen(cmd, shell=True)
        else:
            subprocess.Popen(
                [sys.executable, tool_path, "--account-id", str(account_id)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )

        return {
            "success": True,
            "message": f"🚀 Đang mở cửa sổ lấy token cho {account.email}...",
        }
    except Exception as e:
        logger.error(f"❌ Failed to start extraction: {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi khởi chạy: {str(e)}")


@router.post("/accounts/{account_id}/health-check")
async def trigger_health_check(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Trigger health check thủ công cho 1 account"""
    require_admin(request)

    result = await db.execute(
        select(UltraAccount).where(UltraAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    redis = await get_redis()
    session_mgr = SessionManager(redis)
    is_healthy = await session_mgr.health_check(account.email)

    return {
        "email": account.email,
        "healthy": is_healthy,
        "message": "Token OK" if is_healthy else "Token expired hoặc invalid",
    }


@router.post("/accounts/{account_id}/reset")
async def reset_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Reset account về healthy (clear errors)"""
    require_admin(request)

    await db.execute(
        update(UltraAccount)
        .where(UltraAccount.id == account_id)
        .values(
            status="healthy",
            fail_count=0,
            health_score=100,
            updated_at=datetime.utcnow(),
        )
    )
    await db.commit()

    return {"success": True, "message": "Account đã reset"}


# ═══════════════════════════════════════════════════════════════════════════════
# USERS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/users")
async def list_users(
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
):
    """Danh sách người dùng"""
    require_admin(request)

    result = await db.execute(
        select(User)
        .order_by(desc(User.created_at))
        .limit(limit)
        .offset(offset)
    )
    users = result.scalars().all()

    total = (await db.execute(func.count(User.id))).scalar() or 0

    return {
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "balance": u.balance,
                "total_deposit": u.total_deposit,
                "is_banned": u.is_banned,
                "api_key": u.api_key,
                "plan_id": u.plan_id,
                "plan_expires_at": u.plan_expires_at.isoformat() if u.plan_expires_at else None,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
        "total": total,
    }


@router.put("/users/{user_id}/ban")
async def toggle_ban_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Ban/Unban user"""
    require_admin(request)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    new_status = not user.is_banned
    await db.execute(
        update(User).where(User.id == user_id).values(is_banned=new_status)
    )
    await db.commit()

    return {"success": True, "is_banned": new_status}


@router.post("/users/{user_id}/balance")
async def adjust_balance(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Admin điều chỉnh số dư user"""
    require_admin(request)

    body = await request.json()
    amount = body.get("amount", 0)
    reason = body.get("reason", "Admin adjustment")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    prev = user.balance
    user.balance = prev + amount

    history = BalanceHistory(
        user_id=user_id,
        previous_amount=prev,
        changed_amount=amount,
        current_amount=user.balance,
        content=reason,
        type="admin",
    )
    db.add(history)
    await db.commit()

    return {"success": True, "new_balance": user.balance}


# ═══════════════════════════════════════════════════════════════════════════════
# SYSTEM SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/settings")
async def get_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Lấy hết system settings"""
    require_admin(request)

    result = await db.execute(select(SystemSetting))
    settings_list = result.scalars().all()

    settings_dict = {s.key: s.value for s in settings_list}
    return {"settings": settings_dict}


@router.put("/settings")
async def update_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Cập nhật system settings (key-value pairs)"""
    require_admin(request)

    body = await request.json()
    settings_data = body.get("settings", {})

    for key, value in settings_data.items():
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = str(value)
        else:
            db.add(SystemSetting(key=key, value=str(value)))

    await db.commit()
    return {"success": True}


# ═══════════════════════════════════════════════════════════════════════════════
# LOGS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/logs")
async def get_logs(
    request: Request,
    db: AsyncSession = Depends(get_db),
    type: str = Query("jobs", regex="^(jobs|balance|errors)$"),
    limit: int = Query(50, le=200),
):
    """Xem logs — jobs, balance history, hoặc errors"""
    require_admin(request)

    if type == "jobs":
        result = await db.execute(
            select(GenerationJob)
            .order_by(desc(GenerationJob.created_at))
            .limit(limit)
        )
        jobs = result.scalars().all()
        return {
            "type": "jobs",
            "logs": [
                {
                    "id": j.id,
                    "user_id": j.user_id,
                    "prompt": j.prompt[:80],
                    "status": j.status,
                    "progress_percent": j.progress_percent,
                    "cost": j.cost,
                    "error": j.error,
                    "model_key": j.model_key,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                    "finished_at": j.finished_at.isoformat() if j.finished_at else None,
                }
                for j in jobs
            ],
        }

    elif type == "balance":
        result = await db.execute(
            select(BalanceHistory)
            .order_by(desc(BalanceHistory.created_at))
            .limit(limit)
        )
        entries = result.scalars().all()
        return {
            "type": "balance",
            "logs": [
                {
                    "id": e.id,
                    "user_id": e.user_id,
                    "type": e.type,
                    "previous_amount": e.previous_amount,
                    "changed_amount": e.changed_amount,
                    "current_amount": e.current_amount,
                    "content": e.content,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in entries
            ],
        }

    elif type == "errors":
        result = await db.execute(
            select(GenerationJob)
            .where(GenerationJob.status == "failed")
            .order_by(desc(GenerationJob.created_at))
            .limit(limit)
        )
        jobs = result.scalars().all()
        return {
            "type": "errors",
            "logs": [
                {
                    "id": j.id,
                    "user_id": j.user_id,
                    "prompt": j.prompt[:60],
                    "error": j.error,
                    "model_key": j.model_key,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                }
                for j in jobs
            ],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# PER-ACCOUNT STATS  
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/accounts/{account_id}/stats")
async def get_account_stats(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Thống kê chi tiết cho 1 account: jobs, thành công, thất bại, biểu đồ 7 ngày"""
    require_admin(request)

    # Get account
    result = await db.execute(
        select(UltraAccount).where(UltraAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Total jobs
    total = (await db.execute(
        select(func.count(GenerationJob.id)).where(GenerationJob.account_id == account_id)
    )).scalar() or 0

    # Success
    success = (await db.execute(
        select(func.count(GenerationJob.id)).where(
            GenerationJob.account_id == account_id,
            GenerationJob.status == "completed",
        )
    )).scalar() or 0

    # Failed
    failed = (await db.execute(
        select(func.count(GenerationJob.id)).where(
            GenerationJob.account_id == account_id,
            GenerationJob.status == "failed",
        )
    )).scalar() or 0

    # Active (queued/pending/processing)
    active = (await db.execute(
        select(func.count(GenerationJob.id)).where(
            GenerationJob.account_id == account_id,
            GenerationJob.status.in_(["queued", "pending", "processing"]),
        )
    )).scalar() or 0

    # Daily breakdown (last 7 days)
    from datetime import timedelta
    daily = []
    for i in range(6, -1, -1):
        day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
        day_end = day_start + timedelta(days=1)

        day_success = (await db.execute(
            select(func.count(GenerationJob.id)).where(
                GenerationJob.account_id == account_id,
                GenerationJob.status == "completed",
                GenerationJob.created_at >= day_start,
                GenerationJob.created_at < day_end,
            )
        )).scalar() or 0

        day_failed = (await db.execute(
            select(func.count(GenerationJob.id)).where(
                GenerationJob.account_id == account_id,
                GenerationJob.status == "failed",
                GenerationJob.created_at >= day_start,
                GenerationJob.created_at < day_end,
            )
        )).scalar() or 0

        daily.append({
            "date": day_start.strftime("%d/%m"),
            "success": day_success,
            "failed": day_failed,
        })

    # Recent jobs (last 10)
    recent_result = await db.execute(
        select(GenerationJob)
        .where(GenerationJob.account_id == account_id)
        .order_by(desc(GenerationJob.created_at))
        .limit(10)
    )
    recent = [
        {
            "id": j.id,
            "prompt": j.prompt[:50],
            "status": j.status,
            "error": j.error[:80] if j.error else None,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
        }
        for j in recent_result.scalars().all()
    ]

    return {
        "account_id": account_id,
        "email": account.email,
        "total_jobs": total,
        "successful": success,
        "failed": failed,
        "active": active,
        "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        "daily": daily,
        "recent_jobs": recent,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TOKEN REFRESH LOG — For NanoExt log panel
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/nano-ext/token-log")
async def get_token_refresh_log(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return token status for all accounts — used by the admin log panel"""
    require_admin(request)

    result = await db.execute(
        select(UltraAccount).order_by(UltraAccount.id)
    )
    accounts = result.scalars().all()

    logs = []
    for acc in accounts:
        has_token = bool(acc.bearer_token)
        expires_at = acc.token_expires_at.isoformat() if acc.token_expires_at else None
        last_refresh = acc.last_refresh_at.isoformat() if acc.last_refresh_at else None

        # Calculate remaining time
        remaining_sec = None
        if acc.token_expires_at:
            diff = (acc.token_expires_at - datetime.utcnow()).total_seconds()
            remaining_sec = max(0, int(diff))

        logs.append({
            "id": acc.id,
            "email": acc.email,
            "has_token": has_token,
            "token_preview": f"ya29...{acc.bearer_token[-8:]}" if acc.bearer_token else None,
            "expires_at": expires_at,
            "remaining_seconds": remaining_sec,
            "last_refresh_at": last_refresh,
            "status": acc.status,
        })

    return {"logs": logs}


# ═══════════════════════════════════════════════════════════════════════════════
# SUBSCRIPTION PLANS CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/plans")
async def list_plans(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Danh sách tất cả gói đăng ký"""
    require_admin(request)

    result = await db.execute(
        select(SubscriptionPlan).order_by(SubscriptionPlan.sort_order)
    )
    plans = result.scalars().all()

    return {
        "plans": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "credits": p.credits,
                "price": p.price,
                "duration_days": p.duration_days,
                "max_concurrent": p.max_concurrent,
                "features": p.features,
                "is_active": p.is_active,
                "sort_order": p.sort_order,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in plans
        ]
    }


@router.post("/plans")
async def create_plan(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Tạo gói đăng ký mới"""
    require_admin(request)
    body = await request.json()

    plan = SubscriptionPlan(
        name=body["name"],
        description=body.get("description", ""),
        credits=body["credits"],
        price=body["price"],
        duration_days=body.get("duration_days", 30),
        max_concurrent=body.get("max_concurrent", 4),
        features=body.get("features", {}),
        is_active=body.get("is_active", True),
        sort_order=body.get("sort_order", 0),
    )
    db.add(plan)
    await db.commit()

    logger.info(f"📦 Plan created: {plan.name} — {plan.credits}cr/{plan.price}đ")
    return {"success": True, "id": plan.id, "message": f"Đã tạo gói {plan.name}"}


@router.put("/plans/{plan_id}")
async def update_plan(
    plan_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Cập nhật gói đăng ký"""
    require_admin(request)
    body = await request.json()

    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    updatable = ["name", "description", "credits", "price", "duration_days", "max_concurrent", "features", "is_active", "sort_order"]
    for field in updatable:
        if field in body:
            setattr(plan, field, body[field])

    plan.updated_at = datetime.utcnow()
    await db.commit()

    logger.info(f"✏️ Plan updated: {plan.name}")
    return {"success": True, "message": f"Đã cập nhật gói {plan.name}"}


@router.delete("/plans/{plan_id}")
async def delete_plan(
    plan_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Xóa gói đăng ký"""
    require_admin(request)

    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")

    await db.delete(plan)
    await db.commit()

    logger.info(f"🗑️ Plan deleted: {plan.name}")
    return {"success": True, "message": f"Đã xóa gói {plan.name}"}


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Thay đổi role user (customer/admin)"""
    require_admin(request)
    body = await request.json()
    new_role = body.get("role", "customer")
    if new_role not in ("customer", "admin"):
        raise HTTPException(status_code=400, detail="Invalid role")

    await db.execute(
        update(User).where(User.id == user_id).values(role=new_role)
    )
    await db.commit()
    return {"success": True, "role": new_role}
