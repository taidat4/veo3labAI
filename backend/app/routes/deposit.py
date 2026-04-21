"""
Deposit Routes — MBBank auto-payment for Veo3Lab
User tạo yêu cầu nạp → QR code → chuyển khoản → auto cộng credits

⚠️ QUAN TRỌNG: MBBank API rất dễ bị khóa nếu query liên tục!
- Chỉ query khi có pending deposit (user đã bấm "Đã chuyển khoản")
- Cooldown 30s giữa các lần query cùng token
- Frontend poll mỗi 15s, max 20 lần
"""
import secrets
import logging
import time
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, Column, Integer, String, DateTime, Float
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import async_session_factory, Base, engine
from app.config import get_settings
from app.mbbank_service import get_mbbank_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/deposit", tags=["Deposit"])
settings = get_settings()

DEPOSIT_EXPIRY_MINUTES = 15
CREDIT_RATE = 1000  # 1000 VND = 1 credit (admin có thể chỉnh)

# ── Cooldown cache: chống spam MBBank API ──
# { token: last_query_timestamp }
_mbbank_cooldown: dict[str, float] = {}
MBBANK_COOLDOWN_SECONDS = 30  # Tối thiểu 30s giữa mỗi lần query MBBank


# ── Models ──

class PendingDeposit(Base):
    __tablename__ = "pending_deposits"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(50), unique=True, index=True)
    user_id = Column(Integer, index=True)
    amount = Column(Integer)  # VND
    credits = Column(Integer)  # Credits to add
    content = Column(String(200))  # Nội dung chuyển khoản
    status = Column(String(20), default="pending")  # pending | completed | expired
    bank_txn_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    completed_at = Column(DateTime, nullable=True)


class BankTransaction(Base):
    __tablename__ = "bank_transactions"
    __table_args__ = {"extend_existing": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    txn_id = Column(String(100), unique=True, index=True)
    user_id = Column(Integer)
    amount = Column(Integer)
    credits = Column(Integer)
    bank_time = Column(String(50))
    bank_content = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Auto-migrate ──

async def ensure_deposit_tables():
    """Create deposit tables if not exist"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ── Endpoints ──

@router.post("/request")
async def request_deposit(request: Request):
    """Tạo yêu cầu nạp tiền — trả QR code MBBank"""
    user = get_current_user(request)
    user_id = user["user_id"]

    # Parse body
    body = await request.json()
    amount = body.get("amount", 0)

    if amount < 10000:
        raise HTTPException(400, detail="Số tiền tối thiểu 10,000 VND")
    if amount > 50_000_000:
        raise HTTPException(400, detail="Số tiền tối đa 50,000,000 VND")

    # Tính credits
    credits = amount // CREDIT_RATE

    # Tạo token unique
    token = f"VEO{secrets.token_hex(6).upper()}"
    transfer_content = f"VEO3 {user_id} {token}"
    expires_at = datetime.utcnow() + timedelta(minutes=DEPOSIT_EXPIRY_MINUTES)

    # Lưu vào DB
    async with async_session_factory() as session:
        pending = PendingDeposit(
            token=token,
            user_id=user_id,
            amount=amount,
            credits=credits,
            content=transfer_content,
            expires_at=expires_at,
        )
        session.add(pending)
        await session.commit()

    # QR URL
    safe_content = transfer_content.replace(" ", "%20")
    qr_url = f"https://img.vietqr.io/image/MB-{settings.MBBANK_ACCOUNT}-compact.png?amount={amount}&addInfo={safe_content}"

    logger.info(f"💳 Deposit request: user={user_id}, amount={amount}, credits={credits}, token={token}")

    return {
        "success": True,
        "token": token,
        "amount": amount,
        "credits": credits,
        "qr_url": qr_url,
        "bank_name": settings.MBBANK_NAME,
        "bank_account": settings.MBBANK_ACCOUNT,
        "transfer_content": transfer_content,
        "expires_at": expires_at.isoformat(),
        "message": f"Chuyển khoản đúng số tiền và nội dung trong vòng {DEPOSIT_EXPIRY_MINUTES} phút",
    }


@router.post("/verify/{token}")
async def verify_deposit(token: str, request: Request):
    """
    Kiểm tra giao dịch MBBank có khớp không → cộng credits.
    ⚠️ Có cooldown 30s — không query MBBank liên tục!
    """
    user = get_current_user(request)

    async with async_session_factory() as session:
        result = await session.execute(
            select(PendingDeposit).where(
                PendingDeposit.token == token,
                PendingDeposit.user_id == user["user_id"],
            )
        )
        pending = result.scalar_one_or_none()

        if not pending:
            raise HTTPException(404, detail="Token không tồn tại")

        # Already completed
        if pending.status == "completed":
            return {"success": True, "status": "completed", "message": "Đã nạp thành công"}

        # Expired
        if datetime.utcnow() > pending.expires_at:
            pending.status = "expired"
            await session.commit()
            return {"success": False, "status": "expired", "message": "Mã nạp tiền đã hết hạn"}

        # ── Cooldown check: chống spam MBBank ──
        now = time.time()
        last_query = _mbbank_cooldown.get(token, 0)
        if now - last_query < MBBANK_COOLDOWN_SECONDS:
            remaining = int(MBBANK_COOLDOWN_SECONDS - (now - last_query))
            logger.debug(f"⏳ Cooldown active for token {token}, {remaining}s remaining")
            return {
                "success": False,
                "status": "pending",
                "message": f"Đang chờ thanh toán... (kiểm tra lại sau {remaining}s)",
                "cooldown": remaining,
            }

        # ── Query MBBank (rate-limited) ──
        _mbbank_cooldown[token] = now  # Mark query time BEFORE calling
        try:
            mbbank = get_mbbank_service()
            matched_tx = await mbbank.check_deposit(pending.content, pending.amount)

            if matched_tx:
                tx_id = matched_tx.get("transaction_id", f"auto_{token}")

                # Check duplicate
                existing = await session.execute(
                    select(BankTransaction).where(BankTransaction.txn_id == tx_id)
                )
                if existing.scalar_one_or_none():
                    return {"success": True, "status": "completed", "message": "Giao dịch đã được xử lý"}

                # Mark completed
                pending.status = "completed"
                pending.bank_txn_id = tx_id
                pending.completed_at = datetime.utcnow()

                # Save bank transaction
                bank_txn = BankTransaction(
                    txn_id=tx_id,
                    user_id=pending.user_id,
                    amount=pending.amount,
                    credits=pending.credits,
                    bank_time=matched_tx.get("transaction_date", ""),
                    bank_content=pending.content,
                )
                session.add(bank_txn)

                # Credit user balance
                from app.models import User
                user_result = await session.execute(
                    select(User).where(User.id == pending.user_id)
                )
                db_user = user_result.scalar_one_or_none()
                if db_user:
                    db_user.balance += pending.credits

                await session.commit()

                # Cleanup cooldown cache
                _mbbank_cooldown.pop(token, None)

                logger.info(f"💰 Deposit completed: user={pending.user_id}, +{pending.credits} credits ({pending.amount} VND)")

                return {
                    "success": True,
                    "status": "completed",
                    "credits": pending.credits,
                    "new_balance": db_user.balance if db_user else 0,
                    "message": f"Nạp thành công! +{pending.credits:,} credits",
                }
            else:
                return {"success": False, "status": "pending", "message": "Đang chờ thanh toán..."}

        except Exception as e:
            logger.error(f"❌ Verify deposit error: {e}")
            return {"success": False, "status": "error", "message": "Lỗi kiểm tra giao dịch"}


@router.get("/status/{token}")
async def get_deposit_status(token: str, request: Request):
    """Xem trạng thái nạp tiền"""
    user = get_current_user(request)

    async with async_session_factory() as session:
        result = await session.execute(
            select(PendingDeposit).where(
                PendingDeposit.token == token,
                PendingDeposit.user_id == user["user_id"],
            )
        )
        pending = result.scalar_one_or_none()

        if not pending:
            raise HTTPException(404, detail="Token không tồn tại")

        # Auto-expire
        if pending.status == "pending" and datetime.utcnow() > pending.expires_at:
            pending.status = "expired"
            await session.commit()

        return {
            "token": token,
            "status": pending.status,
            "amount": pending.amount,
            "credits": pending.credits,
            "completed_at": pending.completed_at.isoformat() if pending.completed_at else None,
        }
