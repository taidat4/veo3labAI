"""
API Routes — Auth (Login/Register)
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, UserRateLimit
from app.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.auth import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Đăng nhập → trả JWT token"""
    result = await db.execute(
        select(User).where(User.username == req.username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Tên đăng nhập hoặc mật khẩu sai")

    if user.is_banned:
        raise HTTPException(status_code=403, detail="Tài khoản bị khóa")

    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
    })

    return TokenResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        role=user.role,
        balance=user.balance,
        credits=getattr(user, 'credits', 0) or 0,
    )


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Đăng ký tài khoản mới"""
    # Check duplicate
    result = await db.execute(
        select(User).where(User.username == req.username)
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Tên đăng nhập đã tồn tại")

    # Tạo user với API key tự động
    import secrets
    user = User(
        username=req.username,
        password_hash=hash_password(req.password),
        email=req.email,
        balance=0,
        role="customer",
        api_key=f"veo3_{secrets.token_hex(24)}",
    )
    db.add(user)
    await db.flush()

    # Tạo rate limit record
    rate_limit = UserRateLimit(user_id=user.id)
    db.add(rate_limit)
    await db.commit()

    token = create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
    })

    return TokenResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
        role=user.role,
        balance=0,
        credits=0,
    )


@router.get("/me")
async def get_me(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Lấy thông tin user hiện tại"""
    from app.auth import get_current_user
    user_data = get_current_user(request)

    result = await db.execute(
        select(User).where(User.id == user_data["user_id"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "balance": user.balance,
        "credits": getattr(user, 'credits', 0) or 0,
        "is_banned": user.is_banned,
        "api_key": user.api_key,
        "plan_id": user.plan_id,
        "plan_expires_at": user.plan_expires_at,
        "created_at": user.created_at,
    }


@router.post("/me/generate-api-key")
async def generate_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Tạo API key mới cho user"""
    from app.auth import get_current_user
    import secrets

    user_data = get_current_user(request)
    result = await db.execute(
        select(User).where(User.id == user_data["user_id"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.api_key = f"uf_{secrets.token_hex(28)}"
    await db.commit()

    return {"api_key": user.api_key}


@router.post("/me/change-password")
async def change_password(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Đổi mật khẩu user"""
    from app.auth import get_current_user

    user_data = get_current_user(request)
    body = await request.json()
    current_password = body.get("current_password", "")
    new_password = body.get("new_password", "")

    if not current_password or not new_password:
        raise HTTPException(status_code=400, detail="Thiếu mật khẩu")

    if len(new_password) < 4:
        raise HTTPException(status_code=400, detail="Mật khẩu mới phải ít nhất 4 ký tự")

    result = await db.execute(
        select(User).where(User.id == user_data["user_id"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Mật khẩu hiện tại không đúng")

    user.password_hash = hash_password(new_password)
    await db.commit()

    return {"success": True, "message": "Đổi mật khẩu thành công"}
