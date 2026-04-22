"""
API Route — Upload Image
Upload ảnh TRỰC TIẾP lên Google Flow Labs API → nhận mediaId cho Image-to-Video
Không qua NanoAI proxy — gọi thẳng aisandbox-pa.googleapis.com
"""
import logging
import base64
import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from app.auth import get_current_user

logger = logging.getLogger("veo3.route.upload")
router = APIRouter(prefix="/api", tags=["Upload"])


@router.post("/upload-image")
async def upload_image(
    request: Request,
    image: UploadFile = File(...),
):
    """Upload ảnh trực tiếp lên Google aisandbox API → nhận mediaId"""
    user_data = get_current_user(request)
    user_id = user_data["user_id"]

    # Validate file
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(400, "Chỉ hỗ trợ file ảnh")

    content = await image.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "Ảnh quá lớn (tối đa 10MB)")

    logger.info(f"📤 Upload image: user={user_id}, size={len(content)}, type={image.content_type}")

    # Get account with valid bearer token
    from app.async_worker import get_account_token
    account = await get_account_token()
    if not account:
        raise HTTPException(503, "Không có tài khoản khả dụng")

    bearer_token = account["token"]
    mime = image.content_type or "image/jpeg"
    b64_image = base64.b64encode(content).decode("utf-8")

    # Call Google's media upload API directly
    upload_url = "https://aisandbox-pa.googleapis.com/v1/media:upload"
    upload_body = {
        "image": {
            "bytesBase64Encoded": b64_image,
            "mimeType": mime,
        }
    }

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "Origin": "https://aisandbox-pa.clients6.google.com",
        "Referer": "https://aisandbox-pa.clients6.google.com/",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(upload_url, json=upload_body, headers=headers)
            logger.info(f"📦 Google upload response: status={resp.status_code}, body={resp.text[:500]}")

            if resp.status_code != 200:
                logger.error(f"❌ Google upload failed: {resp.status_code} - {resp.text[:300]}")
                raise HTTPException(502, f"Google upload failed: {resp.status_code}")

            result = resp.json()

        # Extract mediaId from Google response
        # Google returns: {"name": "media/XXXXX"} or {"mediaId": "XXXXX"}
        media_id = None

        if isinstance(result, dict):
            # Direct mediaId
            media_id = result.get("mediaId") or result.get("media_id")

            # Google format: {"name": "media/CAMaJDBjXXXX"}
            name = result.get("name", "")
            if name and not media_id:
                if name.startswith("media/"):
                    media_id = name.replace("media/", "")
                else:
                    media_id = name

            # Nested formats
            for key in ["data", "result", "response"]:
                inner = result.get(key, {})
                if isinstance(inner, dict) and not media_id:
                    media_id = inner.get("mediaId") or inner.get("media_id")
                    inner_name = inner.get("name", "")
                    if inner_name and not media_id:
                        media_id = inner_name.replace("media/", "")

        if media_id:
            logger.info(f"✅ Uploaded image: mediaId={media_id[:40]}...")
            return {"success": True, "media_id": media_id}
        else:
            logger.warning(f"⚠️ Upload OK but no mediaId in response: {str(result)[:500]}")
            return {"success": False, "detail": "Upload thành công nhưng không nhận được mediaId", "raw": str(result)[:300]}

    except httpx.HTTPError as e:
        logger.error(f"❌ Upload HTTP error: {e}")
        raise HTTPException(502, f"Lỗi kết nối Google: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Upload image error: {e}")
        raise HTTPException(500, f"Lỗi upload: {str(e)}")
