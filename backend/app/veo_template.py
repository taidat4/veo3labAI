"""
Veo API Template — Dễ maintain khi Google update endpoint

File này chứa tất cả API request/response templates cho:
1. Tạo video (batchAsyncGenerateVideoText)
2. Tạo ảnh (batchGenerateImages)
3. Check status (batchCheckAsyncVideoGenerationStatus)
4. Upscale video/image

⚠️ Google update endpoint rất thường xuyên.
Khi có thay đổi, chỉ cần sửa file này, không cần sửa logic worker.

Model keys xác nhận từ network traffic (06/04/2026):
- Video: veo_3_1_t2v_fast, veo_3_1_t2v_lite, veo_3_1_t2v_quality
- Image: NARWHAL (NanoBanana2), GEM_PIX_2 (NanoBananaPro), IMAGEN_4
"""

import random
import time
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

FLOW_API_BASE = "https://aisandbox-pa.googleapis.com"

# Video generation
GENERATE_URL = f"{FLOW_API_BASE}/v1/video:batchAsyncGenerateVideoText"

# Status polling
STATUS_URL = f"{FLOW_API_BASE}/v1/video:batchCheckAsyncVideoGenerationStatus"

# Image generation (project-scoped)
IMAGE_URL_TEMPLATE = f"{FLOW_API_BASE}/v1/projects/{{project_id}}/flowMedia:batchGenerateImages"

# Upscale (create upscale job)
UPSCALE_GENERATE_URL = f"{FLOW_API_BASE}/v1/video:batchAsyncGenerateVideoUpsampleVideo"

# Upscale (legacy)
UPSCALE_URL = f"{FLOW_API_BASE}/v1/video:upscale"

# ── Media types ──
MEDIA_TYPE_VIDEO = "video"
MEDIA_TYPE_IMAGE = "image"

# ── Video Model keys (confirmed from network traffic) ──
VIDEO_MODEL_MAP = {
    # Veo 3.1 series (confirmed from real network traffic April 2026)
    "veo31_fast": "veo_3_1_t2v_fast",          # Fast generation (30 credits)
    "veo31_lite": "veo_3_1_t2v_lite",          # Lite (20 credits)
    "veo31_quality": "veo_3_1_t2v_quality",    # Best quality (100 credits)
    "veo31_fast_lp": "veo_3_1_t2v_lite_low_priority",  # Lite Lower Priority (0 credits / FREE)

    # Legacy keys
    "veo2_fast": "veo_2_fov_fast",
    "veo2_quality": "veo_2_fov_quality",
}

# ── Image Model keys (confirmed from network traffic) ──
IMAGE_MODEL_MAP = {
    "nano_banana_2": "NARWHAL",
    "nano_banana_pro": "GEM_PIX_2",
    "imagen_4": "IMAGEN_4",
}

# ── All models combined ──
ALL_MODEL_MAP = {**VIDEO_MODEL_MAP, **IMAGE_MODEL_MAP}

# ── Aspect ratio ──
VIDEO_ASPECT_RATIO_MAP = {
    "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
    "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
}

IMAGE_ASPECT_RATIO_MAP = {
    "16:9": "IMAGE_ASPECT_RATIO_LANDSCAPE",
    "4:3": "IMAGE_ASPECT_RATIO_FOUR_THREE",
    "1:1": "IMAGE_ASPECT_RATIO_SQUARE",
    "3:4": "IMAGE_ASPECT_RATIO_THREE_FOUR",
    "9:16": "IMAGE_ASPECT_RATIO_PORTRAIT",
}

# ── Pricing (VNĐ per output) ──
MODEL_PRICING = {
    # Video (matched to Google Flow April 2026)
    "veo31_fast_lp": 2000,      # Veo 3.1 - Lite [Lower Priority] (0 credits / FREE)
    "veo31_lite": 3000,         # Veo 3.1 - Lite (20 credits)
    "veo31_fast": 8000,         # Veo 3.1 - Fast (30 credits)
    "veo31_quality": 12000,     # Veo 3.1 - Quality (100 credits)
    # Legacy
    "veo2_fast": 3000,
    "veo2_quality": 6000,
    # Image
    "nano_banana_2": 1000,
    "nano_banana_pro": 1500,
    "imagen_4": 2000,
}

# ── Model display info (matched to Google Flow April 2026) ──
MODEL_INFO = {
    # Video models — matched to Flow dropdown names exactly
    "veo31_fast_lp": {"label": "Veo 3.1 - Lite [Lower Priority]", "type": "video", "badge": "🔊", "credits": 0},
    "veo31_lite": {"label": "Veo 3.1 - Lite", "type": "video", "badge": "🔊", "credits": 20},
    "veo31_fast": {"label": "Veo 3.1 - Fast", "type": "video", "badge": "🔊", "credits": 30},
    "veo31_quality": {"label": "Veo 3.1 - Quality", "type": "video", "badge": "🔊", "credits": 100},
    # Legacy
    "veo2_fast": {"label": "Veo 2 - Fast", "type": "video", "badge": "🚀", "credits": 10},
    "veo2_quality": {"label": "Veo 2 - Quality", "type": "video", "badge": "🎬", "credits": 50},
    # Image models — matched to Flow icons exactly
    "nano_banana_2": {"label": "Nano Banana 2", "type": "image", "badge": "👍", "credits": 0},
    "nano_banana_pro": {"label": "Nano Banana Pro", "type": "image", "badge": "👍", "credits": 0},
    "imagen_4": {"label": "Imagen 4", "type": "image", "badge": "", "credits": 5},
}

def is_image_model(model_key: str) -> bool:
    """Check if model key is an image model"""
    return model_key in IMAGE_MODEL_MAP

def is_video_model(model_key: str) -> bool:
    """Check if model key is a video model"""
    return model_key in VIDEO_MODEL_MAP


# ── Default request headers (matched from real Flow traffic 15/04/2026 Chrome 147) ──
DEFAULT_HEADERS = {
    "Content-Type": "text/plain;charset=UTF-8",
    "Origin": "https://labs.google",
    "Referer": "https://labs.google/",
    "Accept": "*/*",
    "Accept-Language": "vi-VN,vi;q=0.9,fr-FR;q=0.8,fr;q=0.7,en-US;q=0.6,en;q=0.5",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Ch-Ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    # ── Extra Chrome headers (required for reCAPTCHA validation) ──
    "x-browser-channel": "stable",
    "x-browser-copyright": "Copyright 2026 Google LLC. All Rights reserved.",
    "x-browser-validation": "EsmT91Yc2imP58B+tvFt/g1KK/I=",
    "x-browser-year": "2026",
    "x-client-data": "CKmdygEIlqHLAQiFoM0BCOe7zwEYsYrPARjWvc8B",
}


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

def build_generate_request(
    prompt: str,
    aspect_ratio: str = "16:9",
    number_of_outputs: int = 1,
    video_model: str = "veo31_fast",
    seed: Optional[int] = None,
    project_id: Optional[str] = None,
    recaptcha_token: Optional[str] = None,
) -> dict:
    """
    Build request body cho API tạo video.
    Format khớp 100% với real Google Flow traffic (captured April 2026).
    """
    import uuid

    if seed is None:
        seed = random.randint(10000, 99999)

    flow_model_key = VIDEO_MODEL_MAP.get(video_model, "veo_3_1_t2v_lite_low_priority")
    flow_aspect_ratio = VIDEO_ASPECT_RATIO_MAP.get(aspect_ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE")

    # Build clientContext — matches real Flow traffic exactly
    client_context = {
        "tool": "PINHOLE",
        "userPaygateTier": "PAYGATE_TIER_TWO",
        "sessionId": f";{int(time.time() * 1000)}",
    }

    # Add project ID (REQUIRED for model access)
    if project_id:
        client_context["projectId"] = project_id

    # Add reCAPTCHA context (INSIDE clientContext per real traffic)
    if recaptcha_token:
        client_context["recaptchaContext"] = {
            "token": recaptcha_token,
            "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
        }

    body = {
        "mediaGenerationContext": {
            "batchId": str(uuid.uuid4()),
        },
        "clientContext": client_context,
        "requests": [
            {
                "aspectRatio": flow_aspect_ratio,
                "seed": seed + i,
                "textInput": {
                    "structuredPrompt": {
                        "parts": [{"text": prompt}]
                    }
                },
                "videoModelKey": flow_model_key,
                "metadata": {},
            }
            for i in range(number_of_outputs)
        ],
        "useV2ModelConfig": True,
    }

    return body


def build_image_request(
    prompt: str,
    aspect_ratio: str = "1:1",
    number_of_outputs: int = 1,
    image_model: str = "nano_banana_2",
    seed: Optional[int] = None,
    project_id: Optional[str] = None,
    recaptcha_token: Optional[str] = None,
) -> dict:
    """
    Build request body cho API tạo ảnh (NanoBanana, Imagen4).
    ⚠️ Google Flow routes ALL generation through batchAsyncGenerateVideoText.
    Image models use `videoModelKey` field (NOT imageModelKey)!
    Confirmed from real captured traffic 15/04/2026.
    """
    import uuid

    if seed is None:
        seed = random.randint(10000, 99999)

    flow_model_key = IMAGE_MODEL_MAP.get(image_model, "NARWHAL")
    # Image models ALSO use VIDEO_ASPECT_RATIO (same endpoint!)
    video_ar_map = {
        "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "1:1": "VIDEO_ASPECT_RATIO_LANDSCAPE",  # fallback
        "4:3": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "3:4": "VIDEO_ASPECT_RATIO_PORTRAIT",
    }
    flow_aspect_ratio = video_ar_map.get(aspect_ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE")

    # Build clientContext — 100% same as video (confirmed)
    client_context = {
        "tool": "PINHOLE",
        "userPaygateTier": "PAYGATE_TIER_TWO",
        "sessionId": f";{int(time.time() * 1000)}",
    }

    if project_id:
        client_context["projectId"] = project_id

    if recaptcha_token:
        client_context["recaptchaContext"] = {
            "token": recaptcha_token,
            "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB",
        }

    body = {
        "mediaGenerationContext": {
            "batchId": str(uuid.uuid4()),
        },
        "clientContext": client_context,
        "requests": [
            {
                "aspectRatio": flow_aspect_ratio,
                "seed": seed + i,
                "textInput": {
                    "structuredPrompt": {
                        "parts": [{"text": prompt}]
                    }
                },
                # Image models use videoModelKey — same field as video!
                "videoModelKey": flow_model_key,
                "metadata": {},
            }
            for i in range(number_of_outputs)
        ],
        "useV2ModelConfig": True,
    }

    return body


def get_image_url(project_id: str) -> str:
    """
    Get image generation URL.
    ⚠️ Google Flow routes ALL generation through batchAsyncGenerateVideoText.
    flowMedia:batchGenerateImages returns 400 — DO NOT USE.
    """
    return GENERATE_URL  # Same as video endpoint!


def build_status_request(operation_id: str) -> dict:
    """Build request body cho API check status video."""
    return {
        "operations": [
            {
                "operation": {"name": operation_id},
                "status": "MEDIA_GENERATION_STATUS_PENDING",
            }
        ],
    }


def build_upscale_status_request(operation_name: str, project_id: str) -> dict:
    """
    Build request body cho API check upscale status.
    Upscale status uses 'media' array format (NOT 'operations').
    Confirmed from real Google Flow DevTools traffic.
    """
    return {
        "media": [
            {
                "name": operation_name,
                "projectId": project_id,
            }
        ],
    }


def build_upscale_request(media_generation_id: str, resolution: str = "1080p") -> dict:
    """Build request body cho upscale video (legacy)."""
    return {
        "mediaGenerationId": media_generation_id,
        "targetResolution": resolution.upper(),
    }


def build_video_upscale_request(
    media_id: str,
    project_id: str,
    video_model: str = "veo_3_1_t2v_lite_low_priority",
    aspect_ratio: str = "VIDEO_ASPECT_RATIO_LANDSCAPE",
) -> dict:
    """
    Build request body for Google's batchAsyncGenerateVideoUpsampleVideo API.
    This matches real Google Flow DevTools traffic for video upscale.
    """
    import uuid as _uuid

    return {
        "requests": [
            {
                "upsampleVideo": {
                    "name": media_id,
                },
                "videoModelKey": video_model,
                "aspectRatio": aspect_ratio,
                "metadata": {},
            }
        ],
        "clientContext": {
            "tool": "PINHOLE",
            "userPaygateTier": "PAYGATE_TIER_TWO",
            "sessionId": f";{int(time.time() * 1000)}",
            "projectId": project_id,
        },
        "mediaGenerationContext": {
            "batchId": str(_uuid.uuid4()),
        },
        "useV2ModelConfig": True,
    }


def build_auth_headers(bearer_token: str, recaptcha_token: str | None = None) -> dict:
    """Build headers đầy đủ cho API request."""
    headers = {
        **DEFAULT_HEADERS,
        "Authorization": f"Bearer {bearer_token}",
    }
    if recaptcha_token:
        headers["x-recaptcha-token"] = recaptcha_token
    return headers


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSE PARSERS
# ═══════════════════════════════════════════════════════════════════════════════

def parse_generate_response(data: dict) -> dict:
    """Parse response từ API generate video."""
    operations = data.get("operations", [])

    if operations:
        op_list = []
        for op in operations:
            op_name = (
                op.get("operation", {}).get("name")
                or op.get("operand", {}).get("name")
            )
            if op_name:
                op_list.append({"name": op_name, "raw": op})

        if op_list:
            return {"success": True, "operations": op_list, "error": None}

    if data.get("name"):
        return {
            "success": True,
            "operations": [{"name": data["name"], "raw": data}],
            "error": None,
        }

    error_msg = data.get("error", {}).get("message", "Unknown error")
    return {"success": False, "operations": [], "error": error_msg}


def parse_image_response(data: dict) -> dict:
    """Parse response từ API generate image."""
    images = []

    # Pattern: generatedImages array
    gen_images = data.get("generatedImages", [])
    for img in gen_images:
        url = img.get("image", {}).get("fifeUrl") or img.get("fifeUrl")
        media_id = img.get("primaryMediaId") or img.get("mediaGenerationId")
        if url:
            images.append({"download_url": url, "media_id": media_id})

    # Pattern: results array
    results = data.get("results", [])
    for r in results:
        url = r.get("fifeUrl") or r.get("image", {}).get("fifeUrl")
        media_id = r.get("primaryMediaId")
        if url and url not in [i["download_url"] for i in images]:
            images.append({"download_url": url, "media_id": media_id})

    if images:
        return {"success": True, "images": images, "error": None}

    error_msg = data.get("error", {}).get("message", "Unknown error")
    return {"success": False, "images": [], "error": error_msg}


def parse_status_response(data: dict) -> dict:
    """Parse response từ API check status video."""
    operations = data.get("operations", [])
    if not operations:
        return {"done": False, "status": "processing", "videos": [], "progress_estimate": 20}

    op = operations[0]
    op_status = op.get("status") or op.get("operation", {}).get("status", "")
    op_name = op.get("operation", {}).get("name") or op.get("name") or ""

    is_complete = op_status in (
        "MEDIA_GENERATION_STATUS_SUCCESSFUL",
        "MEDIA_GENERATION_STATUS_COMPLETED",
    )
    is_failed = op_status == "MEDIA_GENERATION_STATUS_FAILED"

    videos = []

    def _extract_media_id(entry: dict) -> str:
        """Try many fields to find media_id for upscale."""
        return (
            entry.get("primaryMediaId") or
            entry.get("mediaGenerationId") or
            entry.get("sceneId") or
            entry.get("metadata", {}).get("primaryMediaId") or
            entry.get("metadata", {}).get("mediaGenerationId") or
            entry.get("metadata", {}).get("displayName", {}).get("name", "") or
            ""
        )

    # Pattern 1: entries / data array
    entries = op.get("data") or op.get("entries") or []
    for entry in entries:
        url = entry.get("downloadUrl") or entry.get("video", {}).get("uri") or entry.get("fifeUrl")
        media_id = _extract_media_id(entry)
        if url:
            videos.append({"download_url": url, "media_id": media_id})

    # Pattern 2: top-level operation metadata
    op_meta = op.get("operation", {}).get("metadata", {})
    fife_url = op_meta.get("video", {}).get("fifeUrl")
    if fife_url and not videos:
        media_id = (
            op.get("primaryMediaId") or op.get("sceneId") or
            op.get("mediaGenerationId") or
            op_meta.get("primaryMediaId") or op_meta.get("mediaGenerationId") or
            ""
        )
        videos.append({"download_url": fife_url, "media_id": media_id})

    # Pattern 3: direct downloadUrl
    if op.get("downloadUrl") and not videos:
        videos.append({
            "download_url": op["downloadUrl"],
            "media_id": _extract_media_id(op),
        })

    # Fallback: if we have videos but NO media_id, use operation name
    for v in videos:
        if not v.get("media_id") and op_name:
            v["media_id"] = op_name

    # If SUCCESSFUL but no videos found yet — try deeper extraction
    if is_complete and not videos:
        # Try to get media_id from sceneId or primaryMediaId at top level
        media_id = (
            op.get("sceneId") or op.get("primaryMediaId") or
            op.get("mediaGenerationId") or op_name or ""
        )
        # Video URL may come in a later status poll — mark as done with media_id
        if media_id:
            videos.append({"download_url": "", "media_id": media_id})

    if is_complete:
        return {"done": True, "status": "completed", "videos": videos, "progress_estimate": 100}
    elif is_failed:
        error_msg = (
            op.get("error", {}).get("message")
            or op.get("operation", {}).get("error", {}).get("message")
            or op.get("failureReason")
            or op_status
        )
        return {"done": True, "status": "failed", "videos": [], "progress_estimate": 0, "error": error_msg}
    else:
        progress = _estimate_progress(op_status)
        return {"done": False, "status": "processing", "videos": [], "progress_estimate": progress}


def _estimate_progress(status: str) -> int:
    """Map actual Google status to progress %."""
    status_lower = status.lower() if status else ""
    if "pending" in status_lower:
        return 20
    elif "active" in status_lower:
        return 50
    elif "generating" in status_lower or "running" in status_lower:
        return 60
    elif "rendering" in status_lower or "encoding" in status_lower:
        return 80
    elif "uploading" in status_lower or "finalizing" in status_lower:
        return 90
    else:
        return 30
