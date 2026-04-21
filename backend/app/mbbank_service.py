"""
MBBank Service — Dual approach (ported from working shop-mmo)
1. Try MB Bank Online website (cookie/session) — fastest, most reliable
2. Fallback to apicanhan.com API

Environment variables:
  MBBANK_USERNAME, MBBANK_PASSWORD, MBBANK_ACCOUNT  — required
  MBBANK_API_KEY (= APICANHAN_KEY)                  — for API fallback
  MBBANK_SESSION_ID, MBBANK_TOKEN, MBBANK_COOKIE, MBBANK_DEVICE_ID — for direct website
"""
import httpx
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from app.config import get_settings

logger = logging.getLogger("app.mbbank_service")
settings = get_settings()


class MBBankService:
    """Async service to fetch MBBank transactions — dual approach"""

    def __init__(self):
        self.api_url = settings.MBBANK_API_URL  # apicanhan fallback

    # ─────────────────────────────────────────────────────────────
    # PUBLIC: get_transactions (tries website first, then API)
    # ─────────────────────────────────────────────────────────────

    async def get_transactions(self, limit: int = 20) -> Optional[List[Dict]]:
        """Lấy giao dịch gần đây — ưu tiên MB Bank website, fallback API"""

        # Approach 1: MB Bank website (cookie/session)
        if settings.MBBANK_COOKIE and settings.MBBANK_SESSION_ID:
            try:
                logger.info("[MB] Trying MB Bank website (cookie/session)...")
                txns = await self._fetch_from_website(limit)
                if txns and len(txns) > 0:
                    logger.info(f"✅ Website: got {len(txns)} transactions")
                    return txns
                logger.warning("[MB] Website returned 0 transactions, trying API...")
            except Exception as e:
                logger.warning(f"[MB] Website error: {e}, falling back to API...")

        # Approach 2: apicanhan.com API (fallback)
        try:
            logger.info("[MB] Using apicanhan.com API...")
            txns = await self._fetch_from_apicanhan(limit)
            return txns
        except Exception as e:
            logger.error(f"❌ Both MB methods failed: {e}")
            return None

    # ─────────────────────────────────────────────────────────────
    # Approach 1: MB Bank Online website (cookie/session)
    # ─────────────────────────────────────────────────────────────

    async def _fetch_from_website(self, limit: int = 20) -> Optional[List[Dict]]:
        """Fetch transactions directly from MB Bank Online website"""

        endpoints = [
            "https://online.mbbank.com.vn/api/retail-web-transactionservice/transaction/getTransactionAccountHistory",
            "https://online.mbbank.com.vn/api/retail/transaction-account/get",
            "https://online.mbbank.com.vn/api/retail/transaction/list",
        ]

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin": "https://online.mbbank.com.vn",
            "Referer": "https://online.mbbank.com.vn/",
        }

        if settings.MBBANK_COOKIE:
            headers["Cookie"] = settings.MBBANK_COOKIE
        if settings.MBBANK_SESSION_ID:
            headers["X-Session-Id"] = settings.MBBANK_SESSION_ID
            headers["sessionId"] = settings.MBBANK_SESSION_ID
        if settings.MBBANK_TOKEN:
            headers["Authorization"] = f"Bearer {settings.MBBANK_TOKEN}"
            headers["token"] = settings.MBBANK_TOKEN
        if settings.MBBANK_DEVICE_ID:
            headers["deviceIdCommon"] = settings.MBBANK_DEVICE_ID
            headers["device-id"] = settings.MBBANK_DEVICE_ID

        now = datetime.now()
        from_date = (now - timedelta(days=30)).strftime("%d/%m/%Y")
        to_date = now.strftime("%d/%m/%Y")

        request_body = {
            "accountNo": settings.MBBANK_ACCOUNT,
            "fromDate": from_date,
            "toDate": to_date,
            "historyNumber": "",
            "historyType": "DATE_RANGE",
            "refNo": "",
            "sessionId": settings.MBBANK_SESSION_ID,
            "deviceIdCommon": settings.MBBANK_DEVICE_ID or "",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            for url in endpoints:
                try:
                    logger.info(f"[MB Website] Trying: {url}")
                    resp = await client.post(url, headers=headers, json=request_body)

                    if resp.status_code != 200:
                        logger.warning(f"[MB Website] {url} → HTTP {resp.status_code}")
                        continue

                    data = resp.json()

                    # Parse various response formats
                    transactions = []
                    if isinstance(data, dict):
                        if "data" in data and isinstance(data["data"], list):
                            transactions = data["data"]
                        elif "transactions" in data and isinstance(data["transactions"], list):
                            transactions = data["transactions"]
                        elif "result" in data and isinstance(data["result"], list):
                            transactions = data["result"]
                        elif "transactionHistoryList" in data:
                            transactions = data["transactionHistoryList"]
                    elif isinstance(data, list):
                        transactions = data

                    if transactions:
                        logger.info(f"✅ [MB Website] Got {len(transactions)} from {url}")
                        formatted = []
                        for tx in transactions[:limit]:
                            amount = tx.get("amount", tx.get("creditAmount", 0))
                            tx_type = "IN" if (
                                int(str(amount).replace(",", "").replace(".", "")) >= 0
                                or tx.get("type") == "IN"
                                or tx.get("direction") == "IN"
                                or tx.get("creditAmount")
                            ) else "OUT"

                            formatted.append({
                                "transaction_id": tx.get("refNo", tx.get("transactionId", tx.get("id", ""))),
                                "amount": float(str(abs(int(str(amount).replace(",", "").replace(".", "")))).replace(",", "")),
                                "description": tx.get("description", tx.get("content", tx.get("remark", ""))),
                                "transaction_date": tx.get("transactionDate", tx.get("date", tx.get("createdAt", ""))),
                                "type": tx_type,
                            })
                        return [t for t in formatted if t["type"] == "IN"]

                except Exception as e:
                    logger.warning(f"[MB Website] Error with {url}: {e}")
                    continue

        return None

    # ─────────────────────────────────────────────────────────────
    # Approach 2: apicanhan.com API (fallback)
    # ─────────────────────────────────────────────────────────────

    async def _fetch_from_apicanhan(self, limit: int = 20) -> Optional[List[Dict]]:
        """Fetch transactions via apicanhan.com API"""

        params = {
            "key": settings.MBBANK_API_KEY,
            "username": settings.MBBANK_USERNAME,
            "password": settings.MBBANK_PASSWORD,
            "accountNo": settings.MBBANK_ACCOUNT,
        }

        # Remove empty params
        params = {k: v for k, v in params.items() if v}

        if not params.get("key"):
            logger.error("❌ MBBANK_API_KEY not set — cannot use apicanhan fallback")
            return None

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(self.api_url, params=params)

            if response.status_code == 200:
                data = response.json()

                status = data.get("status")
                all_txns = data.get("transactions", [])
                logger.info(f"📦 apicanhan: status={status}, total_txns={len(all_txns)}")

                # Debug: log first 3 transactions
                for i, t in enumerate(all_txns[:3]):
                    logger.info(
                        f"📦 TX[{i}]: type={t.get('type')} "
                        f"amount={t.get('amount')} "
                        f"desc={str(t.get('description', ''))[:80]}"
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
                    logger.info(f"✅ apicanhan: {len(formatted)} IN transactions")
                    return formatted
                else:
                    msg = data.get("message", "Unknown")
                    logger.warning(f"⚠️ apicanhan: status={status}, message={msg}")
                    logger.warning(f"⚠️ Response keys: {list(data.keys())}")
                    # If status != "success" but has data, try to parse anyway
                    if all_txns:
                        in_txns = [t for t in all_txns if t.get("type") == "IN"]
                        formatted = [
                            {
                                "transaction_id": t.get("transactionID", ""),
                                "amount": float(t.get("amount", 0)),
                                "description": t.get("description", ""),
                                "transaction_date": t.get("transactionDate", ""),
                                "type": "IN",
                            }
                            for t in in_txns[:limit]
                        ]
                        return formatted
                    return None
            else:
                logger.error(f"❌ apicanhan HTTP {response.status_code}: {response.text[:200]}")
                return None

        except Exception as e:
            logger.error(f"❌ apicanhan error: {e}")
            return None

    # ─────────────────────────────────────────────────────────────
    # check_deposit — flexible matching (from shop-mmo)
    # ─────────────────────────────────────────────────────────────

    async def check_deposit(self, content: str, amount: int) -> Optional[Dict]:
        """
        Check if a matching transaction exists.
        Uses flexible matching: amount ±1000đ tolerance, content substring match.
        """
        transactions = await self.get_transactions()

        if not transactions:
            logger.warning(f"[check_deposit] No transactions to match against. content={content}, amount={amount}")
            return None

        def normalize(s: str) -> str:
            return s.upper().replace(" ", "").replace("_", "").replace("-", "")

        content_normalized = normalize(content)

        for tx in transactions:
            tx_desc = str(tx.get("description", ""))
            tx_amount = int(float(tx.get("amount", 0)))

            # Amount match: exact or ±1000đ tolerance (like shop-mmo)
            amount_diff = abs(tx_amount - amount)
            amount_match = amount_diff <= 1000

            if not amount_match:
                continue

            # Content match: substring in either direction
            tx_desc_normalized = normalize(tx_desc)
            content_match = (
                content_normalized in tx_desc_normalized
                or tx_desc_normalized in content_normalized
            )

            if content_match:
                logger.info(f"✅ MATCH! amount={tx_amount} (diff={amount_diff}), desc={tx_desc[:60]}")
                return tx

            # Debug: log near-misses
            if amount_match:
                logger.debug(f"[check_deposit] Amount match but content mismatch: desc={tx_desc[:60]}")

        logger.info(f"[check_deposit] No match found for content={content}, amount={amount}")
        return None

    async def test_connection(self) -> bool:
        """Test MB Bank connection"""
        try:
            txns = await self.get_transactions(limit=1)
            if txns is not None:
                logger.info("✅ MBBank connection OK!")
                return True
            else:
                logger.warning("⚠️ MBBank connection failed")
                return False
        except Exception as e:
            logger.error(f"❌ MBBank connection error: {e}")
            return False


# Singleton
_mbbank_service: Optional[MBBankService] = None


def get_mbbank_service() -> MBBankService:
    global _mbbank_service
    if _mbbank_service is None:
        _mbbank_service = MBBankService()
    return _mbbank_service
