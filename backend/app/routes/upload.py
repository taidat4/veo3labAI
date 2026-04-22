"""
API Route — Upload Image
Upload ảnh lên Google Flow Labs qua NanoAI proxy → nhận mediaId cho Image-to-Video
Sử dụng proxy_google_request (is_proxy=True) để nhận raw Google response
"""
import logging
import base64
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from app.auth import get_current_user

logger = logging.getLogger("veo3.route.upload")
router = APIRouter(prefix="/api", tags=["Upload"])


@router.post("/upload-image")
async def upload_image(
    request: Request,
    image: UploadFile = File(...),
):
    """Upload ảnh lên Google aisandbox qua NanoAI proxy → nhận mediaId"""
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

    # Build upload body for Google's media:upload endpoint
    upload_body = {
        "image": {
            "bytesBase64Encoded": b64_image,
            "mimeType": mime,
        }
    }

    try:
        from app.nanoai_client import get_nanoai_client
        nano = get_nanoai_client()

        # Use proxy_google_request (is_proxy=True) to get RAW Google response
        # This forwards directly to Google and returns the response, not a taskId
        result = await nano.proxy_google_request(
            flow_auth_token=bearer_token,
            flow_url="https://aisandbox-pa.googleapis.com/v1/media:upload",
            body_json=upload_body,
        )

        logger.info(f"📦 Upload result: {str(result)[:500]}")

        # Check for NanoAI-level errors
        if result.get("error"):
            logger.error(f"❌ NanoAI proxy error: {result['error']}")
            raise HTTPException(502, f"NanoAI proxy error: {str(result['error'])[:200]}")

        # Extract mediaId from response
        media_id = None

        if isinstance(result, dict):
            # Direct fields
            media_id = result.get("mediaId") or result.get("media_id")

            # Google format: {"name": "media/XXXXX"}
            name = result.get("name", "")
            if name and not media_id:
                media_id = name.replace("media/", "") if name.startswith("media/") else name

            # Check nested: data, result, response
            for key in ["data", "result", "response"]:
                inner = result.get(key, {})
                if isinstance(inner, dict) and not media_id:
                    media_id = inner.get("mediaId") or inner.get("media_id")
                    inner_name = inner.get("name", "")
                    if inner_name and not media_id:
                        media_id = inner_name.replace("media/", "") if inner_name.startswith("media/") else inner_name

            # NanoAI may wrap in success/taskId format — use taskId as fallback
            if not media_id:
                task_id = result.get("taskId")
                if task_id:
                    # Poll the task to get the actual Google response
                    logger.info(f"🔄 Got taskId={task_id}, polling for Google response...")
                    poll_result = await nano.poll_flow_task(task_id, max_polls=10, interval=2)
                    if poll_result:
                        logger.info(f"📦 Poll result: {str(poll_result)[:500]}")
                        media_id = poll_result.get("mediaId") or poll_result.get("media_id")
                        poll_name = poll_result.get("name", "")
                        if poll_name and not media_id:
                            media_id = poll_name.replace("media/", "") if poll_name.startswith("media/") else poll_name

        if media_id:
            logger.info(f"✅ Uploaded image: mediaId={media_id[:40]}...")
            return {"success": True, "media_id": media_id}
        else:
            logger.warning(f"⚠️ Upload OK but no mediaId: {str(result)[:500]}")
            return {"success": False, "detail": "Upload thành công nhưng không nhận được mediaId", "raw": str(result)[:300]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Upload image error: {type(e).__name__}: {e}")
        raise HTTPException(500, f"Lỗi upload: {str(e)}")
