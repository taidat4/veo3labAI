"""
MBBank Service - API Cá Nhân Integration (FULL config)
Gửi đầy đủ sessionId, token, cookie, deviceid cho apicanhan.com
để giải captcha và lấy giao dịch MBBank
"""
import httpx
import logging
from typing import List, Dict, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class MBBankService:
    """Service để gọi API Cá Nhân MBBank (async) — FULL params"""

    def __init__(self):
        self.api_url = settings.MBBANK_API_URL

    async def get_transactions(self, limit: int = 20) -> Optional[List[Dict]]:
        """Lấy danh sách giao dịch gần đây từ MBBank"""
        try:
            # Only send essential params (matching working MY-BOT config)
            params = {
                "key": settings.MBBANK_API_KEY,
                "username": settings.MBBANK_USERNAME,
                "password": settings.MBBANK_PASSWORD,
                "accountNo": settings.MBBANK_ACCOUNT,
            }

            # Add optional params only if set
            for extra_key, extra_val in [
                ("sessionId", settings.MBBANK_SESSION_ID),
                ("id_run", settings.MBBANK_ID_RUN),
                ("token", settings.MBBANK_TOKEN),
                ("cookie", settings.MBBANK_COOKIE),
                ("deviceid", settings.MBBANK_DEVICE_ID),
            ]:
                if extra_val:
                    params[extra_key] = extra_val

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(self.api_url, params=params)

            if response.status_code == 200:
                data = response.json()

                # DEBUG: Log raw response structure
                status = data.get("status")
                all_txns = data.get("transactions", [])
                logger.info(f"📦 MBBank raw: status={status}, total_txns={len(all_txns)}")
                if all_txns:
                    in_count = len([t for t in all_txns if t.get("type") == "IN"])
                    out_count = len([t for t in all_txns if t.get("type") != "IN"])
                    logger.info(f"📦 MBBank: IN={in_count}, OUT={out_count}")
                    # Log first 3 transactions for debug
                    for i, t in enumerate(all_txns[:3]):
                        logger.info(f"📦 TX[{i}]: type={t.get('type')} amount={t.get('amount')} desc={t.get('description','')[:80]}")

                if status == "success" and "transactions" in data:
                    transactions = data["transactions"]
                    in_transactions = [t for t in transactions if t.get("type") == "IN"]

                    formatted = []
                    for t in in_transactions[:limit]:
                        formatted.append({
                            "transaction_id": t.get("transactionID", ""),
                            "amount": float(t.get("amount", 0)),
                            "description": t.get("description", ""),
                            "transaction_date": t.get("transactionDate", ""),
                            "type": "IN",
                        })

                    logger.info(f"✅ Lấy được {len(formatted)} giao dịch IN từ MBBank")
                    return formatted
                else:
                    error_msg = data.get("message", "Unknown error")
                    logger.warning(f"⚠️ API MBBank trả về: status={status}, message={error_msg}")
                    logger.warning(f"⚠️ Full response keys: {list(data.keys())}")
                    return None
            else:
                logger.error(f"❌ Lỗi HTTP {response.status_code} từ API MBBank")
                logger.error(f"❌ Response body: {response.text[:200]}")
                return None

        except Exception as e:
            logger.error(f"❌ Lỗi khi gọi API MBBank: {e}")
            return None

    async def check_deposit(self, content: str, amount: int) -> Optional[Dict]:
        """Kiểm tra xem có giao dịch khớp với content và amount không"""
        transactions = await self.get_transactions()

        if not transactions:
            return None

        def normalize(s: str) -> str:
            return s.upper().replace(" ", "").replace("_", "")

        content_normalized = normalize(content)

        for tx in transactions:
            tx_desc = tx.get("description", "")
            tx_amount = tx.get("amount", 0)

            if int(tx_amount) != amount:
                continue

            tx_desc_normalized = normalize(tx_desc)
            if content_normalized in tx_desc_normalized:
                logger.info(f"✅ Tìm thấy giao dịch khớp: {tx}")
                return tx

        return None

    async def test_connection(self) -> bool:
        """Kiểm tra kết nối API MBBank"""
        try:
            transactions = await self.get_transactions(limit=1)
            if transactions is not None:
                logger.info("✅ Kết nối API MBBank thành công!")
                return True
            else:
                logger.warning("⚠️ Không thể kết nối API MBBank")
                return False
        except Exception as e:
            logger.error(f"❌ Lỗi kết nối API MBBank: {e}")
            return False


# Singleton
_mbbank_service: Optional[MBBankService] = None


def get_mbbank_service() -> MBBankService:
    global _mbbank_service
    if _mbbank_service is None:
        _mbbank_service = MBBankService()
    return _mbbank_service
