"""
Captcha Solver — Dual Provider: OmoCaptcha + CapSolver

Admin chọn provider trong Settings → Worker đọc từ DB trước mỗi request.
Nếu không có key → skip captcha (non-fatal).

Usage:
    # Sync (trong Celery worker)
    token = solve_recaptcha_sync(action="generate")

    # Async (trong API route)
    token = await solve_recaptcha(action="generate")
"""

import logging
import time
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger("veo3.captcha")
settings = get_settings()

# ── Captcha solve lock ──
# Prevents concurrent captcha solves (rate-limit protection).
# reCAPTCHA tokens are SINGLE-USE — do NOT cache them!
_captcha_lock = None  # asyncio.Lock, created on first use


# ═══════════════════════════════════════════════════════════════════════════════
# PROVIDER DETECTION
# ═══════════════════════════════════════════════════════════════════════════════

def _get_active_provider() -> tuple[str, str]:
    """
    Detect active captcha provider.
    Priority: DB setting > env CAPTCHA_PROVIDER > auto-detect from keys.
    Returns: (provider_name, api_key)
    """
    # Try reading from DB (SystemSetting table)
    try:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from app.models import SystemSetting

        engine = create_engine(settings.sync_db_url)
        with Session(engine) as session:
            row = session.execute(
                select(SystemSetting).where(SystemSetting.key == "captcha_provider")
            ).scalar_one_or_none()
            if row and row.value:
                provider = row.value.lower().strip()
                if provider == "2captcha" and settings.TWOCAPTCHA_API_KEY:
                    return ("2captcha", settings.TWOCAPTCHA_API_KEY)
                if provider == "capsolver" and settings.CAPSOLVER_API_KEY:
                    return ("capsolver", settings.CAPSOLVER_API_KEY)
                elif provider == "omocaptcha" and settings.OMOCAPTCHA_API_KEY:
                    return ("omocaptcha", settings.OMOCAPTCHA_API_KEY)
    except Exception:
        pass

    # Fallback: env setting
    provider = settings.CAPTCHA_PROVIDER.lower()
    if provider == "2captcha" and settings.TWOCAPTCHA_API_KEY:
        return ("2captcha", settings.TWOCAPTCHA_API_KEY)
    if provider == "capsolver" and settings.CAPSOLVER_API_KEY:
        return ("capsolver", settings.CAPSOLVER_API_KEY)
    if provider == "omocaptcha" and settings.OMOCAPTCHA_API_KEY:
        return ("omocaptcha", settings.OMOCAPTCHA_API_KEY)

    # Auto-detect: OmoCaptcha > 2captcha > CapSolver (Enterprise pass rate order)
    if settings.OMOCAPTCHA_API_KEY:
        return ("omocaptcha", settings.OMOCAPTCHA_API_KEY)
    if settings.TWOCAPTCHA_API_KEY:
        return ("2captcha", settings.TWOCAPTCHA_API_KEY)
    if settings.CAPSOLVER_API_KEY:
        return ("capsolver", settings.CAPSOLVER_API_KEY)

    return ("none", "")


# ═══════════════════════════════════════════════════════════════════════════════
# OMOCAPTCHA SOLVER
# ═══════════════════════════════════════════════════════════════════════════════

OMOCAPTCHA_CREATE_URL = "https://api.omocaptcha.com/v2/createTask"
OMOCAPTCHA_RESULT_URL = "https://api.omocaptcha.com/v2/getTaskResult"

def _solve_omocaptcha_sync(
    api_key: str,
    site_key: str,
    page_url: str,
    action: str = "",
    proxy: Optional[str] = None,
) -> Optional[str]:
    """Giải reCAPTCHA Enterprise v3 bằng OmoCaptcha (sync) — API v2"""
    task = {
        "type": "RecaptchaV3TokenTask",
        "websiteURL": page_url,
        "websiteKey": site_key,
        "isEnterprise": True,
        "pageAction": action or "VIDEO_GENERATION",
    }

    payload = {"clientKey": api_key, "task": task}

    with httpx.Client(timeout=30) as client:
        resp = client.post(OMOCAPTCHA_CREATE_URL, json=payload)
        data = resp.json()

    if data.get("errorId") and data["errorId"] != 0:
        logger.error(f"OmoCaptcha createTask error: {data.get('errorCode')} - {data.get('errorDescription')}")
        return None

    task_id = data.get("taskId")
    if not task_id:
        logger.error(f"OmoCaptcha no taskId: {data}")
        return None

    logger.info(f"⏳ OmoCaptcha task created: {task_id}")

    # Poll for result (max 30s — enterprise captcha should be fast)
    for i in range(10):
        time.sleep(3)
        with httpx.Client(timeout=15) as client:
            resp = client.post(OMOCAPTCHA_RESULT_URL, json={"clientKey": api_key, "taskId": task_id})
            result = resp.json()

        status = result.get("status", "unknown")
        error_id = result.get("errorId", 0)

        if status == "ready":
            token = result.get("solution", {}).get("gRecaptchaResponse")
            if token:
                logger.info(f"✅ OmoCaptcha solved ({i*3}s): {token[:40]}...")
                return token
            else:
                logger.error(f"OmoCaptcha ready but no token: {result}")
                return None

        if error_id and error_id != 0:
            logger.error(f"OmoCaptcha FAIL: {result.get('errorCode')} - {result.get('errorDescription')}")
            return None

        if status == "fail":
            logger.error(f"OmoCaptcha task failed: {result}")
            return None

        # Log every 5th poll (15s)
        if i % 5 == 0:
            logger.info(f"⏳ OmoCaptcha polling... ({i*3}s) status={status} errorId={error_id} full={result}")

    logger.error("OmoCaptcha timeout (2 min)")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# CAPSOLVER SOLVER
# ═══════════════════════════════════════════════════════════════════════════════

CAPSOLVER_CREATE_URL = "https://api.capsolver.com/createTask"
CAPSOLVER_RESULT_URL = "https://api.capsolver.com/getTaskResult"

def _solve_capsolver_sync(
    api_key: str,
    site_key: str,
    page_url: str,
    action: str = "",
    proxy: Optional[str] = None,
) -> Optional[str]:
    """Giải reCAPTCHA v3 Enterprise bằng CapSolver (sync)"""
    task = {
        "type": "ReCaptchaV3EnterpriseTaskProxyLess",
        "websiteURL": page_url,
        "websiteKey": site_key,
        "pageAction": action or "VIDEO_GENERATION",
        "minScore": 0.9,
    }

    payload = {"clientKey": api_key, "task": task}

    logger.info(f"🔐 CapSolver createTask: type={task['type']}, url={page_url}, key={site_key[:20]}...")

    with httpx.Client(timeout=30) as client:
        resp = client.post(CAPSOLVER_CREATE_URL, json=payload)
        data = resp.json()

    if data.get("errorId") and data["errorId"] != 0:
        logger.error(f"CapSolver createTask error: {data.get('errorCode')} - {data.get('errorDescription')}")
        return None

    task_id = data.get("taskId")
    if not task_id:
        logger.error(f"CapSolver no taskId: {data}")
        return None

    logger.info(f"⏳ CapSolver task created: {task_id}")

    # Poll for result (max 90s, 1s interval per docs)
    for i in range(90):
        time.sleep(1)
        with httpx.Client(timeout=15) as client:
            resp = client.post(CAPSOLVER_RESULT_URL, json={"clientKey": api_key, "taskId": task_id})
            result = resp.json()

        status = result.get("status", "")

        if status == "ready":
            token = result.get("solution", {}).get("gRecaptchaResponse")
            if token:
                logger.info(f"✅ CapSolver solved ({i}s): {token[:40]}...")
                return token
            else:
                logger.error(f"CapSolver ready but no token: {result}")
                return None

        if status == "failed" or (result.get("errorId") and result["errorId"] != 0):
            logger.error(f"CapSolver FAIL: {result.get('errorCode')} - {result.get('errorDescription')}")
            return None

        # Log every 10s
        if i % 10 == 0:
            logger.info(f"⏳ CapSolver polling... ({i}s) status={status}")

    logger.error("CapSolver timeout (90s)")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# 2CAPTCHA SOLVER
# ═══════════════════════════════════════════════════════════════════════════════

TWOCAPTCHA_CREATE_URL = "https://api.2captcha.com/createTask"
TWOCAPTCHA_RESULT_URL = "https://api.2captcha.com/getTaskResult"

def _solve_2captcha_sync(
    api_key: str,
    site_key: str,
    page_url: str,
    action: str = "",
    proxy: Optional[str] = None,
) -> Optional[str]:
    """Giải reCAPTCHA Enterprise v3 bằng 2captcha (sync)"""
    task = {
        "type": "RecaptchaV3TaskProxyless",
        "websiteURL": page_url,
        "websiteKey": site_key,
        "minScore": 0.9,
        "isEnterprise": True,
    }
    if action:
        task["pageAction"] = action

    payload = {"clientKey": api_key, "task": task}

    with httpx.Client(timeout=30) as client:
        resp = client.post(TWOCAPTCHA_CREATE_URL, json=payload)
        data = resp.json()

    if data.get("errorId") and data["errorId"] != 0:
        logger.error(f"2captcha createTask error: {data.get('errorCode')} - {data.get('errorDescription')}")
        return None

    task_id = data.get("taskId")
    if not task_id:
        logger.error(f"2captcha no taskId: {data}")
        return None

    logger.info(f"⏳ 2captcha task created: {task_id}")

    # Poll for result (max 90s)
    for i in range(30):
        time.sleep(3)
        with httpx.Client(timeout=15) as client:
            resp = client.post(TWOCAPTCHA_RESULT_URL, json={"clientKey": api_key, "taskId": task_id})
            result = resp.json()

        status = result.get("status", "")
        error_id = result.get("errorId", 0)

        if status == "ready":
            solution = result.get("solution", {})
            token = solution.get("gRecaptchaResponse") or solution.get("token")
            if token:
                logger.info(f"✅ 2captcha solved ({i*3}s): {token[:40]}...")
                return token
            else:
                logger.error(f"2captcha ready but no token: {result}")
                return None

        if error_id and error_id != 0:
            logger.error(f"2captcha FAIL: {result.get('errorCode')} - {result.get('errorDescription')}")
            return None

        # Log every 5th poll
        if i % 5 == 0:
            logger.info(f"⏳ 2captcha polling... ({i*3}s) status={status}")

    logger.error("2captcha timeout (90s)")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def solve_recaptcha_sync(
    action: str = "VIDEO_GENERATION",
    proxy: Optional[str] = None,
) -> Optional[str]:
    """
    Giải reCAPTCHA Enterprise — Auto-detect provider (sync).
    Returns gRecaptchaResponse token hoặc None.
    """
    provider, api_key = _get_active_provider()

    if provider == "none" or not api_key:
        logger.info("⚠️ No captcha provider configured — skipping")
        return None

    logger.info(f"🔐 Solving reCAPTCHA via {provider}...")

    try:
        if provider == "2captcha":
            return _solve_2captcha_sync(
                api_key=api_key,
                site_key=settings.RECAPTCHA_SITE_KEY,
                page_url=settings.RECAPTCHA_PAGE_URL,
                action=action,
                proxy=proxy,
            )
        elif provider == "omocaptcha":
            return _solve_omocaptcha_sync(
                api_key=api_key,
                site_key=settings.RECAPTCHA_SITE_KEY,
                page_url=settings.RECAPTCHA_PAGE_URL,
                action=action,
                proxy=proxy,
            )
        elif provider == "capsolver":
            return _solve_capsolver_sync(
                api_key=api_key,
                site_key=settings.RECAPTCHA_SITE_KEY,
                page_url=settings.RECAPTCHA_PAGE_URL,
                action=action,
                proxy=proxy,
            )
    except Exception as e:
        logger.error(f"❌ Captcha solver error ({provider}): {e}")

    return None


async def solve_recaptcha(
    action: str = "VIDEO_GENERATION",
    proxy: Optional[str] = None,
) -> Optional[str]:
    """
    Async wrapper — chạy sync solver trong thread executor.
    reCAPTCHA tokens are SINGLE-USE — always solve fresh!
    Lock prevents concurrent solves to avoid CapSolver rate-limiting.
    """
    import asyncio
    global _captcha_lock

    if _captcha_lock is None:
        _captcha_lock = asyncio.Lock()

    async with _captcha_lock:
        loop = asyncio.get_event_loop()
        token = await loop.run_in_executor(None, solve_recaptcha_sync, action, proxy)
        return token


def get_captcha_balance() -> dict:
    """Lấy balance từ active provider"""
    provider, api_key = _get_active_provider()

    if provider == "none":
        return {"provider": "none", "balance": 0}

    try:
        if provider == "omocaptcha":
            with httpx.Client(timeout=10) as client:
                resp = client.post("https://api.omocaptcha.com/v2/getBalance", json={"clientKey": api_key})
                data = resp.json()
                return {
                    "provider": "omocaptcha",
                    "balance": data.get("balance", 0),
                    "quantity": data.get("quantity", 0),
                    "error": data.get("errorDescription") if data.get("errorId") else None,
                }

        elif provider == "capsolver":
            with httpx.Client(timeout=10) as client:
                resp = client.post("https://api.capsolver.com/getBalance", json={"clientKey": api_key})
                data = resp.json()
                return {
                    "provider": "capsolver",
                    "balance": data.get("balance", 0),
                    "error": data.get("errorDescription") if data.get("errorId") else None,
                }
    except Exception as e:
        return {"provider": provider, "balance": 0, "error": str(e)}

    return {"provider": provider, "balance": 0}
