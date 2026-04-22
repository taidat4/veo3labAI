"""
API Route — Upload Image
Lưu ảnh lên server → trả về URL công khai
Dùng URL này trong imageUrls khi tạo video/ảnh qua NanoAI V2 API
"""
import os
import logging
import uuid
import time
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from app.auth import get_current_user

logger = logging.getLogger("veo3.route.upload")
router = APIRouter(prefix="/api", tags=["Upload"])

# Upload directory — must match static mount in main.py
# main.py: static_dir = backend/static/ (2 levels up from backend/app/main.py)
# This file: backend/app/routes/upload.py → need 3 levels up to reach backend/
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/upload-image")
async def upload_image(
    request: Request,
    image: UploadFile = File(...),
):
    """Upload ảnh lên server → trả về public URL để dùng làm tham chiếu"""
    user_data = get_current_user(request)
    user_id = user_data["user_id"]

    # Validate file
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(400, "Chỉ hỗ trợ file ảnh")

    content = await image.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "Ảnh quá lớn (tối đa 10MB)")

    # Determine extension
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    ext = ext_map.get(image.content_type, ".jpg")

    # Save with unique name
    filename = f"ref_{user_id}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    logger.info(f"📤 Upload image: user={user_id}, file={filename}, size={len(content)}")

    # Build public URL
    # In production: use the domain; in dev: use relative path
    from app.config import get_settings
    settings = get_settings()

    # The static files are served at /static/ by FastAPI
    image_url = f"/static/uploads/{filename}"

    # For NanoAI V2 API, we need a full public URL
    # Get the host from the request or settings
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    scheme = request.headers.get("x-forwarded-proto") or "https"

    if host:
        public_url = f"{scheme}://{host}/static/uploads/{filename}"
    else:
        public_url = image_url

    logger.info(f"✅ Image saved: {filename}, public_url={public_url}")

    # Cleanup old uploads (keep last 100 files max)
    _cleanup_old_uploads()

    return {
        "success": True,
        "media_id": filename,  # Use filename as the "mediaId" for reference
        "url": image_url,
        "public_url": public_url,
    }


def _cleanup_old_uploads(max_files: int = 100, max_age_hours: int = 48):
    """Remove old uploaded files to prevent disk bloat"""
    try:
        files = []
        now = time.time()
        for f in os.listdir(UPLOAD_DIR):
            fpath = os.path.join(UPLOAD_DIR, f)
            if os.path.isfile(fpath):
                mtime = os.path.getmtime(fpath)
                age_hours = (now - mtime) / 3600
                files.append((fpath, mtime, age_hours))

        # Remove files older than max_age_hours
        for fpath, mtime, age in files:
            if age > max_age_hours:
                os.remove(fpath)

        # If still too many, remove oldest
        files = [(fp, mt, ag) for fp, mt, ag in files if os.path.exists(fp)]
        if len(files) > max_files:
            files.sort(key=lambda x: x[1])  # oldest first
            for fpath, _, _ in files[:len(files) - max_files]:
                if os.path.exists(fpath):
                    os.remove(fpath)
    except Exception as e:
        logger.warning(f"⚠️ Cleanup error: {e}")
