"""
MBBank Service - API Cá Nhân Integration
Kiểm tra giao dịch nạp tiền qua API apicanhan.com
Adapted for Veo3Lab async architecture
"""
import httpx
import logging
from typing import List, Dict, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class MBBankService:
    """Service để gọi API Cá Nhân MBBank (async)"""

    def __init__(self):
        self.api_url = settings.MBBANK_API_URL

    async def get_transactions(self, limit: int = 20) -> Optional[List[Dict]]:
        """Lấy danh sách giao dịch gần đây từ MBBank"""
        try:
            params = {
                "key": settings.MBBANK_API_KEY,
                "username": settings.MBBANK_USERNAME,
                "password": settings.MBBANK_PASSWORD,
                "accountNo": settings.MBBANK_ACCOUNT,
            }

            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(self.api_url, params=params)

            if response.status_code == 200:
                data = response.json()

                if data.get("status") == "success" and "transactions" in data:
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

                    logger.info(f"✅ Lấy được {len(formatted)} giao dịch từ MBBank")
                    return formatted
                else:
                    error_msg = data.get("message", "Unknown error")
                    logger.warning(f"⚠️ API MBBank trả về lỗi: {error_msg}")
                    return None
            else:
                logger.error(f"❌ Lỗi HTTP {response.status_code} từ API MBBank")
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


# Singleton
_mbbank_service: Optional[MBBankService] = None


def get_mbbank_service() -> MBBankService:
    global _mbbank_service
    if _mbbank_service is None:
        _mbbank_service = MBBankService()
    return _mbbank_service
