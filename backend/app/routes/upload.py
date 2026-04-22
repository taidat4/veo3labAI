"""
API Route — Upload Image
Upload ảnh lên Google Flow để nhận mediaId cho Image-to-Video
"""
import logging
import base64
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from app.auth import get_current_user

logger = logging.getLogger("veo3.route.upload")
router = APIRouter(prefix="/api", tags=["Upload"])


@router.post("/upload-image")
async def upload_image(
    request: Request,
    image: UploadFile = File(...),
):
    """Upload ảnh lên Google Flow Labs qua NanoAI proxy → nhận mediaId"""
    user_data = get_current_user(request)
    user_id = user_data["user_id"]

    # Validate file
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(400, "Chỉ hỗ trợ file ảnh")

    content = await image.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "Ảnh quá lớn (tối đa 10MB)")

    logger.info(f"📤 Upload image: user={user_id}, size={len(content)}, type={image.content_type}")

    # Get account token
    from app.async_worker import get_account_token
    account = await get_account_token()
    if not account:
        raise HTTPException(503, "Không có tài khoản khả dụng")

    # Upload to Google Flow via NanoAI proxy
    from app.nanoai_client import get_nanoai_client
    nano = get_nanoai_client()

    # Encode image to base64
    b64_image = base64.b64encode(content).decode("utf-8")
    mime = image.content_type or "image/jpeg"

    # Extract project_id from account
    project_id = ""
    flow_url = account.get("flow_project_url", "") or ""
    if "/project/" in flow_url:
        project_id = flow_url.split("/project/")[-1].split("?")[0].split("/")[0]

    # Upload via Google's media upload endpoint through NanoAI proxy
    upload_body = {
        "image": {
            "bytesBase64Encoded": b64_image,
            "mimeType": mime,
        },
    }

    try:
        result = await nano.create_flow(
            flow_auth_token=account["token"],
            flow_url="https://aisandbox-pa.googleapis.com/v1/media:upload",
            body_json=upload_body,
        )

        logger.info(f"📦 Upload result: {str(result)[:500]}")

        # Extract mediaId from response
        media_id = None

        # Check multiple possible response formats
        if isinstance(result, dict):
            # Direct mediaId
            media_id = result.get("mediaId") or result.get("media_id")

            # Nested in data
            data = result.get("data", {})
            if isinstance(data, dict) and not media_id:
                media_id = data.get("mediaId") or data.get("media_id")

            # Nested in result
            inner = result.get("result", {})
            if isinstance(inner, dict) and not media_id:
                media_id = inner.get("mediaId") or inner.get("media_id")

            # Check for name field (Google format: "media/CAMaJDBj...")
            name = result.get("name") or (data or {}).get("name") or (inner or {}).get("name")
            if name and not media_id:
                media_id = name.replace("media/", "")

        if media_id:
            logger.info(f"✅ Uploaded image: mediaId={media_id[:30]}...")
            return {"success": True, "media_id": media_id}
        else:
            logger.warning(f"⚠️ Upload succeeded but no mediaId found in response: {str(result)[:500]}")
            return {"success": False, "detail": "Upload thành công nhưng không nhận được mediaId"}

    except Exception as e:
        logger.error(f"❌ Upload image error: {e}")
        raise HTTPException(500, f"Lỗi upload: {str(e)}")
