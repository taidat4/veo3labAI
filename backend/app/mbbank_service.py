"""
MBBank Service — apicanhan.com Integration
apicanhan.com là service giải captcha + lấy giao dịch MBBank
Cần gửi TOÀN BỘ params: key, username, password, accountNo, sessionId, id_run, token, cookie, deviceid, user
"""
import httpx
import logging
from typing import List, Dict, Optional

from app.config import get_settings

logger = logging.getLogger("app.mbbank_service")
settings = get_settings()


class MBBankService:
    """Async MBBank service via apicanhan.com"""

    def __init__(self):
        self.api_url = settings.MBBANK_API_URL

    async def get_transactions(self, limit: int = 20) -> Optional[List[Dict]]:
        """Lấy giao dịch từ MBBank qua apicanhan.com — gửi TOÀN BỘ params"""
        try:
            # PHẢI gửi đầy đủ tất cả params cho apicanhan
            params = {
                "key": settings.MBBANK_API_KEY,
                "username": settings.MBBANK_USERNAME,
                "password": settings.MBBANK_PASSWORD,
                "accountNo": settings.MBBANK_ACCOUNT,
                "user": settings.MBBANK_USERNAME,
                "sessionId": settings.MBBANK_SESSION_ID,
                "id_run": settings.MBBANK_ID_RUN,
                "token": settings.MBBANK_TOKEN,
                "cookie": settings.MBBANK_COOKIE,
                "deviceid": settings.MBBANK_DEVICE_ID,
            }

            # Log params being sent (mask sensitive values)
            logger.info(f"[apicanhan] Sending request with key={params['key'][:8]}..., "
                        f"user={params['username']}, account={params['accountNo']}, "
                        f"sessionId={params.get('sessionId','')[:12]}..., "
                        f"has_token={bool(params.get('token'))}, "
                        f"has_cookie={bool(params.get('cookie'))}, "
                        f"has_deviceid={bool(params.get('deviceid'))}")

            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(self.api_url, params=params)

            logger.info(f"[apicanhan] HTTP {response.status_code}")

            if response.status_code == 200:
                data = response.json()

                status = data.get("status")
                all_txns = data.get("transactions", [])
                logger.info(f"📦 apicanhan: status={status}, total_txns={len(all_txns)}")

                # Debug: log first 5 transactions
                for i, t in enumerate(all_txns[:5]):
                    logger.info(
                        f"📦 TX[{i}]: type={t.get('type')} "
                        f"amount={t.get('amount')} "
                        f"desc={str(t.get('description', ''))[:100]}"
                    )

                if status == "success" and "transactions" in data:
                    in_txns = [t for t in all_txns if t.get("type") == "IN"]
                    formatted = []
                    for t in in_txns[:limit]:
                        formatted.append({
                            "transaction_id": t.get("transactionID", ""),
                            "amount": float(t.get("amount", 0)),
                            "description": t.get("description", ""),
                            "transaction_date": t.get("transactionDate", ""),
                            "type": "IN",
                        })
                    logger.info(f"✅ {len(formatted)} IN transactions found")
                    return formatted
                else:
                    msg = data.get("message", "Unknown")
                    logger.warning(f"⚠️ apicanhan response: status={status}, message={msg}")
                    logger.warning(f"⚠️ Full keys: {list(data.keys())}")
                    # Try to parse anyway if there are transactions
                    if all_txns:
                        in_txns = [t for t in all_txns if t.get("type") == "IN"]
                        return [
                            {
                                "transaction_id": t.get("transactionID", ""),
                                "amount": float(t.get("amount", 0)),
                                "description": t.get("description", ""),
                                "transaction_date": t.get("transactionDate", ""),
                                "type": "IN",
                            }
                            for t in in_txns[:limit]
                        ]
                    return None
            else:
                logger.error(f"❌ HTTP {response.status_code}: {response.text[:300]}")
                return None

        except Exception as e:
            logger.error(f"❌ apicanhan error: {e}")
            return None

    async def check_deposit(self, content: str, amount: int) -> Optional[Dict]:
        """Check matching transaction — flexible matching"""
        transactions = await self.get_transactions()

        if not transactions:
            logger.warning(f"[check] No transactions. content={content}, amount={amount}")
            return None

        def normalize(s: str) -> str:
            return s.upper().replace(" ", "").replace("_", "").replace("-", "")

        content_normalized = normalize(content)

        for tx in transactions:
            tx_desc = str(tx.get("description", ""))
            tx_amount = int(float(tx.get("amount", 0)))

            # Amount: exact or ±1000đ tolerance
            amount_diff = abs(tx_amount - amount)
            if amount_diff > 1000:
                continue

            # Content: substring match both directions
            tx_desc_normalized = normalize(tx_desc)
            if content_normalized in tx_desc_normalized or tx_desc_normalized in content_normalized:
                logger.info(f"✅ MATCH! amount={tx_amount} desc={tx_desc[:60]}")
                return tx

        logger.info(f"[check] No match for content={content}, amount={amount}")
        return None

    async def test_connection(self) -> bool:
        try:
            txns = await self.get_transactions(limit=1)
            ok = txns is not None
            logger.info(f"{'✅' if ok else '❌'} MBBank connection {'OK' if ok else 'FAILED'}")
            return ok
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            return False


# Singleton
_mbbank_service: Optional[MBBankService] = None


def get_mbbank_service() -> MBBankService:
    global _mbbank_service
    if _mbbank_service is None:
        _mbbank_service = MBBankService()
    return _mbbank_service
