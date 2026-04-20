"""
Auth Utilities — JWT token + Admin Secret Key management

2 hệ thống auth tách biệt:
1. User auth: JWT Bearer token (login bằng username/password)
2. Admin auth: Secret key riêng (nhập key vào admin dashboard)
"""

from jose import jwt
from jose.exceptions import JWTError
from datetime import datetime, timedelta
import hashlib
import hmac
from fastapi import Request, HTTPException

from app.config import get_settings

settings = get_settings()


# ═══════════════════════════════════════════════════════════════════════════════
# PASSWORD HASHING
# ═══════════════════════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """Hash password using SHA-256 + salt (simple but secure enough for dev)"""
    salt = settings.JWT_SECRET[:16]
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


# ═══════════════════════════════════════════════════════════════════════════════
# JWT TOKEN (User Auth)
# ═══════════════════════════════════════════════════════════════════════════════

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError as e:
        import logging
        logging.getLogger("veo3.auth").warning(f"JWT decode error: {e}")
        return None
    except Exception as e:
        import logging
        logging.getLogger("veo3.auth").warning(f"JWT unexpected error: {e}")
        return None


def get_current_user(request: Request) -> dict:
    """Lấy user từ JWT token trong header Authorization"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = auth.replace("Bearer ", "")

    payload = decode_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return {
        "user_id": int(payload["sub"]),
        "username": payload.get("username", ""),
        "role": payload.get("role", "customer"),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN SECRET KEY AUTH (Tách biệt hoàn toàn khỏi user auth)
# ═══════════════════════════════════════════════════════════════════════════════

def create_admin_token(secret_key: str) -> str:
    """Tạo JWT token riêng cho admin từ secret key"""
    to_encode = {
        "type": "admin",
        "sub": "admin",
        "role": "admin",
        "exp": datetime.utcnow() + timedelta(hours=12),
    }
    # Dùng secret key khác để sign — hoàn toàn tách biệt khỏi user token
    return jwt.encode(to_encode, settings.ADMIN_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_admin_token(token: str) -> bool:
    """Verify admin token (signed bằng ADMIN_SECRET_KEY, KHÔNG phải JWT_SECRET)"""
    try:
        payload = jwt.decode(token, settings.ADMIN_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("type") == "admin" and payload.get("role") == "admin"
    except Exception:
        return False


def verify_admin_secret(secret_key: str) -> bool:
    """So sánh secret key (constant-time để chống timing attack)"""
    return hmac.compare_digest(secret_key, settings.ADMIN_SECRET_KEY)


def require_admin(request: Request) -> dict:
    """
    Yêu cầu admin auth — kiểm tra ADMIN token (ưu tiên)
    hoặc fallback về user JWT nếu role=admin
    """
    auth = request.headers.get("Authorization", "")

    if auth.startswith("Bearer "):
        token = auth.replace("Bearer ", "")

        # Ưu tiên: Check admin token (signed bằng ADMIN_SECRET_KEY)
        if verify_admin_token(token):
            return {"user_id": 0, "username": "admin", "role": "admin"}

        # Fallback: Check user JWT (signed bằng JWT_SECRET)
        payload = decode_token(token)
        if payload and payload.get("role") == "admin":
            return {
                "user_id": int(payload["sub"]),
                "username": payload.get("username", ""),
                "role": "admin",
            }

    # Check X-Admin-Key header
    admin_key = request.headers.get("X-Admin-Key", "")
    if admin_key and verify_admin_secret(admin_key):
        return {"user_id": 0, "username": "admin", "role": "admin"}

    raise HTTPException(status_code=403, detail="Admin access required")
