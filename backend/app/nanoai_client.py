"""
NanoAI Client — Unified API
============================
Handles both:
  - Flow Proxy (/api/fix/) — Video generation via Google proxy
  - Image API  (/api/v2/) — Direct image generation + upscale

NanoAI xử lý reCAPTCHA nội bộ, không cần CapSolver.

Task Status format:
  Processing: {"success": false, "code": "processing", "message": "Task is being processed"}
  Success:    {"success": true, "code": "success", "data": {"mediaId": "xxx", "mediaUrl": "https://..."}}
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Optional

import httpx

from app.config import get_settings

logger = logging.getLogger("veo3.nanoai")
settings = get_settings()


class NanoAIClient:
    """Unified NanoAI API Client"""

    FIX_BASE = settings.NANOAI_BASE_URL   # https://flow-api.nanoai.pics/api/fix
    V2_BASE = "https://flow-api.nanoai.pics/api/v2"
    GENERATE_URL = "https://aisandbox-pa.googleapis.com/v1/video:batchAsyncGenerateVideoText"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or settings.NANOAI_API_KEY
        if not self.api_key:
            raise ValueError("NANOAI_API_KEY chưa cấu hình!")

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ═══════════════════════════════════════════════════════════════
    # VIDEO — Flow Proxy (/api/fix/)
    # ═══════════════════════════════════════════════════════════════

    async def create_flow(
        self,
        flow_auth_token: str,
        body_json: dict,
        flow_url: str = "",
        is_proxy: bool = False,
    ) -> dict:
        """Gửi video request qua NanoAI flow proxy."""
        if not flow_url:
            flow_url = self.GENERATE_URL

        payload = {
            "flow_url": flow_url,
            "flow_auth_token": flow_auth_token,
            "body_json": body_json,
            "is_proxy": is_proxy,
        }

        logger.info(f"🚀 NanoAI create-flow: model={body_json.get('requests', [{}])[0].get('videoModelKey', '?')}")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.FIX_BASE}/create-flow",
                headers=self._headers,
                json=payload,
            )

        logger.info(f"📡 NanoAI create-flow: HTTP {resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"🔴 NanoAI create-flow error: {resp.text[:500]}")
            return {"error": resp.text[:500], "status_code": resp.status_code}

        data = resp.json()
        logger.info(f"✅ NanoAI create-flow response: {json.dumps(data)[:500]}")
        return data

    async def proxy_google_request(
        self,
        flow_auth_token: str,
        flow_url: str,
        body_json: dict,
    ) -> dict:
        """Forward ANY Google API request through NanoAI proxy to avoid IP blocks.
        Used for status polling, upscale, etc."""
        payload = {
            "flow_url": flow_url,
            "flow_auth_token": flow_auth_token,
            "body_json": body_json,
            "is_proxy": True,  # Always proxy — avoid IP blocks
        }

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{self.FIX_BASE}/create-flow",
                headers=self._headers,
                json=payload,
            )

        if resp.status_code != 200:
            return {"error": resp.text[:500], "status_code": resp.status_code}

        return resp.json()

    async def get_flow_task_status(self, task_id: str) -> dict:
        """Poll flow task status (/api/fix/task-status)."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.FIX_BASE}/task-status",
                params={"taskId": task_id},
                headers=self._headers,
            )

        if resp.status_code == 404:
            return {"success": False, "code": "not_found", "error": "Task not found"}
        if resp.status_code != 200:
            return {"success": False, "code": "error", "error": f"HTTP {resp.status_code}"}

        return resp.json()

    # ═══════════════════════════════════════════════════════════════
    # IMAGE — Direct API (/api/v2/)
    # ═══════════════════════════════════════════════════════════════

    async def create_image(
        self,
        access_token: str,
        prompt: str,
        aspect_ratio: str = "IMAGE_ASPECT_RATIO_LANDSCAPE",
        image_model: str = "GEM_PIX_2",
        image_urls: list = None,
        cookie: str = "",
    ) -> dict:
        """
        Tạo ảnh qua NanoAI v2 API.
        Returns: {"success": true, "taskId": "xxx"} hoặc trực tiếp result.
        """
        payload = {
            "accessToken": access_token,
            "promptText": prompt,
            "imageUrls": image_urls or [],
            "aspectRatio": aspect_ratio,
            "imageModel": image_model,
        }
        if cookie:
            payload["cookie"] = cookie

        logger.info(f"🖼️ NanoAI create-image: model={image_model}, ar={aspect_ratio}, hasCookie={bool(cookie)}")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.V2_BASE}/images/create",
                headers=self._headers,
                json=payload,
            )

        logger.info(f"📡 NanoAI create-image: HTTP {resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"🔴 NanoAI image error: {resp.text[:500]}")
            return {"error": resp.text[:500]}

        data = resp.json()
        logger.info(f"✅ NanoAI image response: {json.dumps(data)[:500]}")
        return data

    async def upscale_image(
        self,
        access_token: str,
        media_id: str,
        project_id: str,
        target_resolution: str = "RESOLUTION_2K",
        cookie: str = "",
    ) -> dict:
        """
        Upscale ảnh qua NanoAI v2 API.
        Returns: {"success": true, "result": {"encodedImage": "base64..."}}
        """
        payload = {
            "accessToken": access_token,
            "mediaId": media_id,
            "projectId": project_id,
            "targetResolution": target_resolution,
        }
        if cookie:
            payload["cookie"] = cookie

        logger.info(f"🔍 NanoAI image upscale: mediaId={media_id[:20]}..., res={target_resolution}, hasCookie={bool(cookie)}")

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.V2_BASE}/images/upscale",
                headers=self._headers,
                json=payload,
            )

        if resp.status_code != 200:
            logger.error(f"🔴 NanoAI image upscale error: {resp.text[:500]}")
            return {"error": resp.text[:500]}

        data = resp.json()
        logger.info(f"✅ NanoAI image upscale done: success={data.get('success')}")
        return data

    async def create_video_v2(
        self,
        access_token: str,
        cookie: str,
        prompt: str,
        aspect_ratio: str = "VIDEO_ASPECT_RATIO_LANDSCAPE",
        video_model: str = "VEO_3_GENERATE",
        image_urls: list = None,
        video_type: str = "frame",
    ) -> dict:
        """
        Tạo video qua NanoAI V2 API (thay vì flow proxy).
        POST /api/v2/videos/create
        Returns: {"success": true, "taskId": "xxx"}
        Task completion returns mediaId UUID compatible with upscale.
        """
        payload = {
            "accessToken": access_token,
            "cookie": cookie,
            "promptText": prompt,
            "imageUrls": image_urls or [],
            "aspectRatio": aspect_ratio,
            "videoModel": video_model,
            "type": video_type,
        }

        logger.info(f"🎬 NanoAI V2 create-video: model={video_model}, ar={aspect_ratio}")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.V2_BASE}/videos/create",
                headers=self._headers,
                json=payload,
            )

        logger.info(f"📡 NanoAI V2 create-video: HTTP {resp.status_code}")

        if resp.status_code != 200:
            logger.error(f"🔴 NanoAI V2 video error: {resp.text[:500]}")
            return {"error": resp.text[:500], "status_code": resp.status_code}

        data = resp.json()
        logger.info(f"✅ NanoAI V2 create-video response: {json.dumps(data)[:500]}")
        return data

    async def upscale_video(
        self,
        access_token: str,
        cookie: str,
        media_id: str,
        project_id: str,
        aspect_ratio: str = "VIDEO_ASPECT_RATIO_LANDSCAPE",
    ) -> dict:
        """
        Upscale video 720p → 1080p qua NanoAI v2 API.
        POST /api/v2/videos/upscale
        Docs: accessToken, cookie, mediaId, projectId, aspectRatio
        Returns: {"success": true, "taskId": "xxx"}
        """
        payload = {
            "accessToken": access_token,
            "cookie": cookie,
            "mediaId": media_id,
            "projectId": project_id,
            "aspectRatio": aspect_ratio,
        }

        logger.info(f"📺 NanoAI video upscale: mediaId={media_id}, ar={aspect_ratio}, hasCookie={bool(cookie)}, cookieLen={len(cookie)}")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.V2_BASE}/videos/upscale",
                headers=self._headers,
                json=payload,
            )

        if resp.status_code != 200:
            logger.error(f"🔴 NanoAI video upscale error: {resp.text[:500]}")
            return {"error": resp.text[:500], "status_code": resp.status_code}

        data = resp.json()
        logger.info(f"✅ NanoAI video upscale response: {json.dumps(data)[:500]}")
        return data

    # ═══════════════════════════════════════════════════════════════
    # TASK STATUS — Unified (/api/v2/task)
    # ═══════════════════════════════════════════════════════════════

    async def get_v2_task_status(self, task_id: str) -> dict:
        """
        Poll v2 task status.
        Response format:
          Processing: {"success": false, "code": "processing", ...}
          Success:    {"success": true, "code": "success", "data": {"mediaId":"...", "mediaUrl":"..."}}
        """
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{self.V2_BASE}/task",
                params={"taskId": task_id},
                headers=self._headers,
            )

        if resp.status_code != 200:
            return {"success": False, "code": "error", "message": f"HTTP {resp.status_code}"}

        return resp.json()

    # ═══════════════════════════════════════════════════════════════
    # POLLERS
    # ═══════════════════════════════════════════════════════════════

    async def poll_v2_task(
        self,
        task_id: str,
        max_polls: int = 60,
        interval: int = 3,
        on_progress=None,
    ) -> dict:
        """
        Poll NanoAI v2 task until success/failed.
        Uses "code" field: "processing" | "success" | "error"
        """
        for i in range(max_polls):
            await asyncio.sleep(interval)

            elapsed = (i + 1) * interval
            progress = min(int((elapsed / 60) * 90), 95)

            if on_progress:
                await on_progress(progress, "processing")

            try:
                result = await self.get_v2_task_status(task_id)
                code = result.get("code", "")
                success = result.get("success", False)

                logger.info(f"📊 NanoAI v2 task {task_id[:16]}: code={code} success={success} ({elapsed}s)")

                if success and code == "success":
                    data = result.get("data", {})
                    # NanoAI image may return URL at various levels
                    # Merge result-level fields into data for easier extraction
                    full_data = {}
                    if isinstance(data, dict):
                        full_data.update(data)
                    # Also check "result" field (nested)
                    inner_result = result.get("result", {})
                    if isinstance(inner_result, dict):
                        full_data.update(inner_result)
                    # Top level fields (mediaId, fileUrl may be here)
                    for key in ("mediaId", "fileUrl", "mediaUrl", "url", "imageUrl", "projectId"):
                        if result.get(key) and not full_data.get(key):
                            full_data[key] = result[key]
                    return {"done": True, "status": "completed", "data": full_data}

                if code in ("error", "failed", "not_found"):
                    error_msg = result.get("message", code)
                    logger.error(f"🔴 NanoAI v2 task {task_id[:16]} FAILED: code={code}, msg={error_msg}, full={json.dumps(result)[:500]}")
                    return {"done": True, "status": "failed", "error": error_msg}

                # "processing" → keep polling

            except Exception as e:
                logger.error(f"⚠️ NanoAI v2 poll error: {e}")

        return {"done": True, "status": "failed", "error": f"Timeout ({max_polls * interval}s)"}

    async def poll_flow_task(
        self,
        task_id: str,
        max_polls: int = 30,
        interval: int = 3,
    ) -> dict | None:
        """
        Poll NanoAI flow task until Google response available.
        Returns Google's raw response or None.
        """
        for i in range(max_polls):
            await asyncio.sleep(interval)

            try:
                result = await self.get_flow_task_status(task_id)
                logger.info(f"📊 NanoAI flow task {task_id[:16]}: {json.dumps(result)[:400]}")

                # NanoAI v2 format: check "code" field
                code = result.get("code", "")
                success = result.get("success", False)

                if success and code == "success":
                    # Check for Google response in data
                    data = result.get("data", {})
                    if data.get("operations"):
                        return data
                    # Also check result field
                    inner = result.get("result", {})
                    if isinstance(inner, dict) and inner.get("operations"):
                        return inner
                    # Return whatever data we got
                    if data:
                        return data

                if code in ("error", "failed", "not_found"):
                    logger.error(f"🔴 NanoAI flow task failed: {result}")
                    return None

                # Check nested for Google operations (any format)
                for key in ["result", "data", "response"]:
                    nested = result.get(key, {})
                    if isinstance(nested, dict) and nested.get("operations"):
                        logger.info(f"✅ Found Google response in '{key}' at poll #{i+1}")
                        return nested

                if result.get("operations"):
                    return result

                # Check if result itself has success + operations
                if result.get("success") and result.get("result"):
                    inner = result["result"]
                    if isinstance(inner, dict) and inner.get("operations"):
                        return inner

            except Exception as e:
                logger.error(f"⚠️ NanoAI flow poll error: {e}")

        logger.error(f"🔴 NanoAI flow task {task_id[:16]} timed out")
        return None

    # ═══════════════════════════════════════════════════════════════
    # BALANCE
    # ═══════════════════════════════════════════════════════════════

    async def get_balance(self) -> dict:
        """Kiểm tra số dư tài khoản NanoAI"""
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{self.FIX_BASE}/balance",
                headers=self._headers,
            )
        if resp.status_code != 200:
            return {"error": resp.text[:300]}
        return resp.json()


# ═══════════════════════════════════════════════════════════════════════════════
# BODY BUILDER — Video (for flow proxy)
# ═══════════════════════════════════════════════════════════════════════════════

def build_nanoai_body(
    prompt: str,
    aspect_ratio: str = "16:9",
    video_model: str = "veo_3_1_t2v_lite_low_priority",
    project_id: str = "",
    seed: Optional[int] = None,
) -> dict:
    """Build body_json cho NanoAI create-flow."""
    import random

    if seed is None:
        seed = random.randint(1000, 99999)

    ar_map = {
        "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "1:1": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "4:3": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "3:4": "VIDEO_ASPECT_RATIO_PORTRAIT",
    }

    return {
        "clientContext": {
            "recaptchaToken": "",
            "sessionId": f";{int(time.time() * 1000)}",
            "projectId": project_id,
            "tool": "PINHOLE",
            "userPaygateTier": "PAYGATE_TIER_TWO",
        },
        "requests": [
            {
                "aspectRatio": ar_map.get(aspect_ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE"),
                "seed": seed,
                "textInput": {
                    "prompt": prompt,
                },
                "videoModelKey": video_model,
                "metadata": {
                    "sceneId": str(uuid.uuid4()),
                },
            }
        ],
    }


def build_nanoai_upscale_body(
    media_generation_id: str,
    aspect_ratio: str = "16:9",
    project_id: str = "",
) -> dict:
    """
    Build body_json cho NanoAI create-flow UPSCALE (720p → 1080p).
    Confirmed correct format via API probing:
      - videoInput.mediaId = UUID of source video
      - videoModelKey = veo_3_1_upsampler_1080p
      - NO audioReference (rejected by Google)
      - NO videoGenerationVideoInputs (rejected by Google)
    
    Protobuf type: google.internal.labs.aisandbox.proto.videofx.v1.VideoGenerationVideoInput
    """
    ar_map = {
        "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "1:1": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "4:3": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "3:4": "VIDEO_ASPECT_RATIO_PORTRAIT",
    }

    return {
        "clientContext": {
            "sessionId": f";{int(time.time() * 1000)}",
            "projectId": project_id,
            "tool": "PINHOLE",
            "userPaygateTier": "PAYGATE_TIER_TWO",
        },
        "requests": [
            {
                "aspectRatio": ar_map.get(aspect_ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE"),
                "seed": 0,
                "videoModelKey": "veo_3_1_upsampler_1080p",
                "metadata": {},
                "videoInput": {
                    "mediaId": media_generation_id,
                },
            }
        ],
    }


# Aspect ratio mapping for NanoAI v2 Image API
IMAGE_AR_MAP = {
    "16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "4:3": "IMAGE_ASPECT_RATIO_FOUR_THREE",
    "1:1": "IMAGE_ASPECT_RATIO_SQUARE",
    "3:4": "IMAGE_ASPECT_RATIO_THREE_FOUR",
    "9:16": "IMAGE_ASPECT_RATIO_PORTRAIT",
}


_client: Optional[NanoAIClient] = None


def get_nanoai_client() -> NanoAIClient:
    global _client
    if _client is None:
        _client = NanoAIClient()
    return _client
