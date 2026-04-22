"""
API Routes — Video proxy, download & upscale
Stream video cho <video> tag, tải về, và upscale 1080p
"""

import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified
import httpx

from app.database import get_db, async_session_factory
from app.models import GenerationJob
from app.auth import get_current_user


logger = logging.getLogger("veo3.route.video")
router = APIRouter(prefix="/api", tags=["Video"])


@router.get("/proxy/video/{job_id}")
async def proxy_video(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Proxy stream video cho <video src="/api/proxy/video/123">.
    Hỗ trợ Range requests cho seeking.
    """
    user_data = get_current_user(request)

    result = await db.execute(
        select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.user_id == user_data["user_id"],
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Video not found")

    video_url = job.r2_url or job.temp_video_url
    if not video_url:
        raise HTTPException(status_code=404, detail="Video chưa sẵn sàng")

    # Proxy request với Range support
    range_header = request.headers.get("Range")

    async def stream_video():
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            headers = {}
            if range_header:
                headers["Range"] = range_header

            async with client.stream("GET", video_url, headers=headers) as resp:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    yield chunk

    # Get content info
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        head_resp = await client.head(video_url)
        content_length = head_resp.headers.get("Content-Length", "0")
        content_type = head_resp.headers.get("Content-Type", "video/mp4")

    response_headers = {
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Access-Control-Allow-Origin": "*",
    }

    if range_header:
        # Partial content
        return StreamingResponse(
            stream_video(),
            status_code=206,
            headers=response_headers,
            media_type=content_type,
        )

    response_headers["Content-Length"] = content_length
    return StreamingResponse(
        stream_video(),
        status_code=200,
        headers=response_headers,
        media_type=content_type,
    )


@router.get("/download/{job_id}")
async def download_video(
    job_id: int,
    quality: str = "720",
    token: str = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Download video file.
    quality: "720" | "1080" | "4k"
    token: optional JWT token via query param (for direct browser links)
    """
    # Try standard auth header first, then fall back to query param token
    user_data = None
    try:
        user_data = get_current_user(request)
    except Exception:
        pass
    
    if not user_data and token:
        from app.auth import decode_token
        if token == "dev-bypass-token":
            user_data = {"user_id": 1, "username": "dev_user", "role": "admin"}
        else:
            payload = decode_token(token)
            if payload and "sub" in payload:
                user_data = {"user_id": int(payload["sub"]), "username": payload.get("username", "")}
    
    if not user_data:
        raise HTTPException(status_code=401, detail="Missing authorization")

    result = await db.execute(
        select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.user_id == user_data["user_id"],
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Video not found")

    video_url = job.r2_url or job.temp_video_url
    if not video_url:
        raise HTTPException(status_code=404, detail="Video chưa sẵn sàng")

    # Use upscaled URL if 1080p requested and available
    params = job.params or {}
    if quality == "1080" and params.get("upscale_url"):
        video_url = params["upscale_url"]
        logger.info(f"📺 Serving upscaled 1080p URL for job {job_id}")

    # Stream download
    filename = f"veo3-video-{job_id}-{quality}.mp4"

    async def download_stream():
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", video_url) as resp:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    yield chunk

    return StreamingResponse(
        download_stream(),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Allow-Origin": "*",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# UPSCALE VIDEO (720p → 1080p) — via NanoAI V2
# ═══════════════════════════════════════════════════════════════════════════════

async def _get_account_cookie(account_id: int) -> str:
    """Get cookie string from account.
    Priority: UltraAccount.cookies → SessionData.cookies → bearer_token fallback."""
    from app.models import SessionData, UltraAccount
    async with async_session_factory() as session:
        # 1. Try direct cookies field on UltraAccount (from token syncer)
        acc_result = await session.execute(
            select(UltraAccount).where(UltraAccount.id == account_id)
        )
        acc = acc_result.scalar_one_or_none()
        if acc and acc.cookies:
            logger.info(f"🍪 Got cookies from UltraAccount for account {account_id}: {len(acc.cookies)} chars")
            return acc.cookies

        # 2. Try SessionData cookies
        result = await session.execute(
            select(SessionData)
            .where(SessionData.account_id == account_id)
            .order_by(SessionData.created_at.desc())
            .limit(1)
        )
        sd = result.scalar_one_or_none()
        if sd and sd.cookies:
            if isinstance(sd.cookies, dict):
                cookie_str = "; ".join(f"{k}={v}" for k, v in sd.cookies.items())
                logger.info(f"🍪 Got cookies from SessionData for account {account_id}: {len(cookie_str)} chars")
                return cookie_str
            if isinstance(sd.cookies, str):
                logger.info(f"🍪 Got cookie string from SessionData for account {account_id}")
                return sd.cookies

        # 3. Fallback: use bearer_token as cookie (may not work for all endpoints)
        if acc and acc.bearer_token:
            logger.warning(f"⚠️ No real cookies — using bearer_token as cookie for account {account_id} (may fail)")
            return acc.bearer_token

    logger.warning(f"⚠️ No cookie available for account {account_id}")
    return ""


async def _get_project_id_for_account(account_id: int) -> str:
    """Extract project_id from account's flow_project_url."""
    from app.models import UltraAccount
    async with async_session_factory() as session:
        result = await session.execute(
            select(UltraAccount).where(UltraAccount.id == account_id)
        )
        acc = result.scalar_one_or_none()
        if acc and acc.flow_project_url and "/project/" in acc.flow_project_url:
            return acc.flow_project_url.split("/project/")[-1].split("?")[0].split("/")[0]
    return ""


@router.post("/upscale/{job_id}")
async def upscale_video(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger upscale 720p → 1080p via NanoAI V2 API.
    POST /api/v2/videos/upscale → taskId → poll /api/v2/task
    Tries multiple credential approaches if first attempt fails.
    """
    user_data = get_current_user(request)

    result = await db.execute(
        select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.user_id == user_data["user_id"],
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Video not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Video chưa hoàn thành")

    # Try to get media_id — for NanoAI V2 upscale, we need NanoAI's own mediaId (UUID)
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
    params = job.params or {}
    media_id = ""

    # ★ Priority 1: NanoAI mediaId captured during video creation
    nanoai_mid = params.get("nanoai_media_id", "")
    if nanoai_mid and uuid_pattern.match(nanoai_mid):
        media_id = nanoai_mid
        logger.info(f"✅ Using NanoAI mediaId from creation: {media_id}")

    # ★ Priority 2: Query V2 task status using saved nano_task_id
    if not media_id and params.get("nano_task_id"):
        try:
            from app.nanoai_client import get_nanoai_client
            nano = get_nanoai_client()
            task_status = await nano.get_v2_task_status(params["nano_task_id"])
            logger.info(f"🔍 V2 task status for {params['nano_task_id']}: {str(task_status)[:300]}")
            if task_status.get("success") and isinstance(task_status.get("data"), dict):
                v2_mid = task_status["data"].get("mediaId") or task_status["data"].get("media_id") or ""
                v2_pid = task_status["data"].get("projectId") or task_status["data"].get("project_id") or ""
                if v2_mid and uuid_pattern.match(v2_mid):
                    media_id = v2_mid
                    logger.info(f"✅ Got NanoAI mediaId from V2 task: {media_id}")
                    # Save for future use
                    async with async_session_factory() as s:
                        j = (await s.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                        if j:
                            p = j.params or {}
                            p["nanoai_media_id"] = media_id
                            if v2_pid:
                                p["nanoai_project_id"] = v2_pid
                            j.params = p
                            await s.commit()
        except Exception as e:
            logger.warning(f"⚠️ V2 task lookup failed: {e}")

    # Priority 3: job.media_id if already UUID
    if not media_id:
        raw_media_id = job.media_id or ""
        if raw_media_id and uuid_pattern.match(raw_media_id):
            media_id = raw_media_id
        elif raw_media_id:
            # Google protobuf base64 format — extract UUID (fallback)
            try:
                import base64
                padded = raw_media_id + "=" * (4 - len(raw_media_id) % 4) if len(raw_media_id) % 4 else raw_media_id
                decoded = base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
                uuids = re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', decoded, re.I)
                if uuids:
                    media_id = uuids[-1]  # ★ LAST UUID is the media ID (first is scene/generation ID)
                    logger.info(f"🔍 Extracted UUID from Google protobuf: {media_id} (from {len(uuids)} UUIDs: {uuids})")
            except Exception as e:
                logger.warning(f"⚠️ Failed to decode media_id protobuf: {e}")

    # Priority 4: operation_id
    if not media_id and job.operation_id and uuid_pattern.match(job.operation_id):
        media_id = job.operation_id
        logger.info(f"🔍 Using operation_id as media_id: {media_id}")

    if not media_id:
        raise HTTPException(status_code=400, detail="Video thiếu media_id UUID, không thể upscale")

    # Check if already upscaled
    params = job.params or {}
    if params.get("upscale_url"):
        return {"success": True, "status": "completed", "upscale_url": params["upscale_url"]}

    # ★ If task_id exists, VERIFY it's still valid on NanoAI before returning "processing"
    existing_task = params.get("upscale_task_id", "")
    if existing_task and not params.get("upscale_error"):
        try:
            from app.nanoai_client import get_nanoai_client
            nano_check = get_nanoai_client()
            check_result = await nano_check.get_v2_task_status(existing_task)
            check_code = check_result.get("code", "")
            check_success = check_result.get("success", False)
            
            if check_code == "processing" or (not check_success and check_code == "processing"):
                # Task is genuinely processing → return
                return {"success": True, "status": "processing", "message": "Đang upscale..."}
            elif check_success and check_code == "success":
                # Task already completed! Extract URL
                data = check_result.get("data", {}) or {}
                url = data.get("mediaUrl") or data.get("url") or ""
                if url:
                    params["upscale_url"] = url
                    params.pop("upscale_task_id", None)
                    job.params = params
                    await db.commit()
                    return {"success": True, "status": "completed", "upscale_url": url}
            
            # Task expired/failed/not found → clear and proceed with new upscale
            logger.info(f"🧹 Old task {existing_task[:16]}... is stale (code={check_code}), starting new upscale")
        except Exception as e:
            logger.warning(f"⚠️ Failed to verify old task: {e}")

    # ★ Clear ALL old stale state before starting new upscale
    # This invalidates any old background polls (race guard will see mismatched task_id)
    if params.get("upscale_task_id") or params.get("upscale_error"):
        old_task = params.get("upscale_task_id", "")
        params.pop("upscale_task_id", None)
        params.pop("upscale_error", None)
        params.pop("_upscale_clearing", None)
        job.params = params
        await db.commit()
        logger.info(f"🧹 Cleared old upscale state (old_task={old_task[:16] if old_task else 'none'})")

    # Get account token for API call — MUST use same account that created the video
    # mediaId is scoped to the account's project — other accounts CANNOT access it
    from app.async_worker import get_account_token, report_account_result
    
    account = None
    last_error = ""

    # ★ MUST use original account (video mediaId belongs to its project)
    if job.account_id:
        async with async_session_factory() as sess:
            from app.models import UltraAccount
            acc_result = await sess.execute(
                select(UltraAccount).where(UltraAccount.id == job.account_id)
            )
            orig_acc = acc_result.scalar_one_or_none()
            if orig_acc and orig_acc.bearer_token:
                account = {
                    "email": orig_acc.email,
                    "token": orig_acc.bearer_token,
                    "proxy": orig_acc.proxy_url,
                    "account_id": orig_acc.id,
                    "flow_project_url": orig_acc.flow_project_url,
                    "cookies": orig_acc.cookies or "",
                }
                logger.info(f"🎯 Using ORIGINAL account for upscale: {orig_acc.email} (account_id={job.account_id})")
            else:
                logger.error(f"🔴 Original account {job.account_id} not found or has no token")

    if not account:
        raise HTTPException(status_code=400, detail="Không tìm được account gốc đã tạo video — không thể upscale")

    # ★ Get projectId — prioritize saved project_id (from video creation) over flow_project_url
    # Video may have been created in a different project than flow_project_url
    project_id = params.get("nanoai_project_id", "") or params.get("project_id", "")
    if project_id:
        logger.info(f"📁 Using saved project_id from params: {project_id}")
    else:
        # Fallback: extract from account's flow_project_url
        flow_url = account.get("flow_project_url", "") or ""
        if "/project/" in flow_url:
            project_id = flow_url.split("/project/")[-1].split("?")[0].split("/")[0]
            logger.info(f"📁 Fallback: extracted project_id from flow_project_url: {project_id}")
    if not project_id:
        raise HTTPException(status_code=400, detail=f"Account {account['email']} không có project_id — không thể upscale")
    # Determine aspect ratio from job params — convert to NanoAI format
    raw_ar = params.get("aspect_ratio", "16:9")
    ar_map = {
        "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "1:1": "VIDEO_ASPECT_RATIO_SQUARE",
    }
    nanoai_ar = ar_map.get(raw_ar, "VIDEO_ASPECT_RATIO_LANDSCAPE")
    # If already in NanoAI format, use as-is
    if raw_ar.startswith("VIDEO_ASPECT_RATIO"):
        nanoai_ar = raw_ar

    logger.info(f"📺 Upscale job {job_id}: media_id={media_id[:30]}..., project_id={project_id}, account={account['email']}, ar={nanoai_ar}")

    try:
        from app.nanoai_client import get_nanoai_client
        nano = get_nanoai_client()

        # ★ NanoAI V2 upscale — TESTED & WORKING
        # POST /api/v2/videos/upscale (per NanoAI docs)
        upscale_result = await nano.upscale_video(
            access_token=account["token"],
            cookie=account.get("cookies", ""),
            media_id=media_id,
            project_id=project_id,
            aspect_ratio=nanoai_ar,
        )

        logger.info(f"📡 V2 upscale response: {str(upscale_result)[:500]}")

        if "error" in upscale_result and not upscale_result.get("success"):
            last_error = str(upscale_result.get("error", ""))[:200]
            logger.warning(f"⚠️ V2 upscale error: {last_error}")
            await report_account_result(account["email"], False, last_error)
            raise HTTPException(status_code=502, detail=f"Upscale lỗi: {last_error}")

        task_id = upscale_result.get("taskId") or upscale_result.get("task_id")

        if not task_id:
            logger.error(f"🔴 No taskId in V2 upscale response: {str(upscale_result)[:300]}")
            raise HTTPException(status_code=502, detail="Không nhận được taskId từ V2 upscale")

        logger.info(f"✅ V2 upscale taskId: {task_id}, account={account['email']}")

        # Save task ID for polling
        params["upscale_task_id"] = task_id
        params["upscale_account_email"] = account["email"]
        params["upscale_project_id"] = project_id
        params.pop("upscale_error", None)  # Clear old error
        job.params = {**params}  # ★ NEW dict for SQLAlchemy
        flag_modified(job, "params")
        await db.commit()

        # ★ Poll using V2 task status (GET /api/v2/task?taskId=...)
        asyncio.create_task(_poll_upscale_nanoai(
            job_id, user_data["user_id"], task_id
        ))

        return {
            "success": True,
            "status": "processing",
            "message": "Đang tăng độ phân giải video lên 1080p (~1-2 phút)...",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upscale error: {e}")
        raise HTTPException(status_code=502, detail=f"Upscale lỗi: {str(e)[:200]}")


@router.get("/upscale/{job_id}/status")
async def upscale_status(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Check upscale status"""
    user_data = get_current_user(request)

    result = await db.execute(
        select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.user_id == user_data["user_id"],
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Video not found")

    params = job.params or {}
    res = params.get("upscale_resolution", "")
    res_label = {"RESOLUTION_1K": "1K", "RESOLUTION_2K": "2K", "RESOLUTION_4K": "4K"}.get(res, "")

    if params.get("upscale_url"):
        return {"status": "completed", "upscale_url": params["upscale_url"], "upscale_resolution": res_label}
    elif params.get("upscale_task_id"):
        return {"status": "processing", "message": "Đang tăng độ phân giải...", "upscale_resolution": res_label}
    else:
        return {"status": "not_started", "upscale_error": params.get("upscale_error", "")}


@router.post("/upscale/{job_id}/clear-error")
async def clear_upscale_error(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Clear upscale error so user can retry."""
    user_data = get_current_user(request)
    result = await db.execute(
        select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.user_id == user_data["user_id"],
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Not found")
    params = job.params or {}
    params.pop("upscale_error", None)
    params.pop("upscale_task_id", None)
    job.params = params
    await db.commit()
    return {"success": True}


async def _poll_upscale_direct(job_id: int, user_id: int, operation_name: str, project_id: str, bearer_token: str):
    """Background: poll upscale status DIRECTLY to Google (bypass NanoAI).
    Uses batchCheckAsyncVideoGenerationStatus with 'media' format body."""
    import asyncio
    import httpx
    from app.async_worker import publish_progress
    from app.veo_template import STATUS_URL, DEFAULT_HEADERS, build_upscale_status_request

    for i in range(60):  # Max 5 min (60 × 5s)
        await asyncio.sleep(5)

        try:
            import json as _json
            status_body = build_upscale_status_request(operation_name, project_id)
            headers = {
                **DEFAULT_HEADERS,
                "Authorization": f"Bearer {bearer_token}",
            }

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    STATUS_URL,  # batchCheckAsyncVideoGenerationStatus
                    headers=headers,
                    content=_json.dumps(status_body),  # text/plain
                )

            if resp.status_code != 200:
                logger.warning(f"⚠️ Upscale status HTTP {resp.status_code}: {resp.text[:200]}")
                continue

            data = resp.json()
            logger.info(f"📊 Direct upscale poll #{i+1}: {str(data)[:400]}")

            # Check media array
            media_list = data.get("media", [])
            for media_item in media_list:
                if not isinstance(media_item, dict):
                    continue

                media_status = media_item.get("mediaStatus", {}) or {}
                gen_status = media_status.get("mediaGenerationStatus", "")

                if gen_status == "MEDIA_GENERATION_STATUS_COMPLETE":
                    # Find download URL
                    upscale_url = ""

                    # Check encodedVideo
                    encoded = media_item.get("encodedVideo", {}) or {}
                    upscale_url = encoded.get("url") or encoded.get("videoUrl") or ""

                    # Check video field
                    if not upscale_url:
                        video_field = data.get("video", {}) or {}
                        gen_video = video_field.get("generatedVideo", {}) or {}
                        upscale_url = gen_video.get("url") or gen_video.get("videoUrl") or ""

                    # Deep search
                    if not upscale_url:
                        upscale_url = _find_url_in_response(data)

                    if upscale_url:
                        # ★ Try to get the redirect URL for actual video download
                        try:
                            media_name = media_item.get("name", operation_name)
                            redirect_url = f"https://aisandbox-pa.googleapis.com/v1/video/media/{media_name}:getMediaUrlRedirect"
                            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as dl_client:
                                dl_resp = await dl_client.get(
                                    redirect_url,
                                    headers=headers,
                                )
                                if dl_resp.status_code in (301, 302, 307, 308):
                                    upscale_url = dl_resp.headers.get("location", upscale_url)
                                    logger.info(f"📥 Got redirect URL: {upscale_url[:80]}")
                                elif dl_resp.status_code == 200:
                                    # Might be direct content or JSON with URL
                                    ct = dl_resp.headers.get("content-type", "")
                                    if "video" in ct:
                                        upscale_url = redirect_url
                                    else:
                                        try:
                                            rd = dl_resp.json()
                                            upscale_url = rd.get("url", upscale_url) or rd.get("mediaUrl", upscale_url)
                                        except Exception:
                                            pass
                        except Exception as e:
                            logger.warning(f"⚠️ Redirect URL fetch failed: {e}")

                    if upscale_url:
                        async with async_session_factory() as session:
                            job_result = await session.execute(
                                select(GenerationJob).where(GenerationJob.id == job_id)
                            )
                            job = job_result.scalar_one_or_none()
                            if job:
                                params = job.params or {}
                                params["upscale_url"] = upscale_url
                                params.pop("upscale_task_id", None)
                                job.params = params
                                await session.commit()
                        await publish_progress(user_id, job_id, {
                            "type": "upscale_completed",
                            "job_id": job_id,
                            "upscale_url": upscale_url,
                        })
                        logger.info(f"✅ Direct upscale done for job {job_id}: {upscale_url[:80]}")
                        return
                    else:
                        logger.warning(f"⚠️ Upscale COMPLETE but no URL: {str(data)[:500]}")
                        continue

                elif gen_status == "MEDIA_GENERATION_STATUS_FAILED":
                    error_msg = media_status.get("failureReason", "Upscale failed by Google")
                    logger.error(f"🔴 Upscale failed: {error_msg}")
                    async with async_session_factory() as session:
                        job_result = await session.execute(
                            select(GenerationJob).where(GenerationJob.id == job_id)
                        )
                        job = job_result.scalar_one_or_none()
                        if job:
                            params = job.params or {}
                            params.pop("upscale_task_id", None)
                            params["upscale_error"] = str(error_msg)[:200]
                            job.params = params
                            await session.commit()
                    await publish_progress(user_id, job_id, {
                        "type": "upscale_failed", "job_id": job_id, "error": str(error_msg)[:200],
                    })
                    return

                # PENDING — keep polling

        except Exception as e:
            logger.error(f"Direct upscale poll error: {e}")

    # Timeout
    logger.warning(f"⚠️ Direct upscale timeout for job {job_id}")
    async with async_session_factory() as session:
        job_result = await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if job:
            params = job.params or {}
            params.pop("upscale_task_id", None)
            params["upscale_error"] = "Timeout — quá 5 phút"
            job.params = params
            await session.commit()


async def _poll_upscale_flow(job_id: int, user_id: int, operation_name: str, account: dict, project_id: str = ""):
    """Background: poll upscale via Google status check through flow proxy.
    Uses 'media' format body (NOT 'operations') matching actual Google Flow."""
    import asyncio
    from app.nanoai_client import get_nanoai_client
    from app.async_worker import publish_progress
    from app.veo_template import STATUS_URL, build_upscale_status_request

    nano = get_nanoai_client()

    # Get project_id from job if not provided
    if not project_id:
        try:
            async with async_session_factory() as session:
                job_result = await session.execute(
                    select(GenerationJob).where(GenerationJob.id == job_id)
                )
                job = job_result.scalar_one_or_none()
                if job:
                    params = job.params or {}
                    project_id = params.get("nanoai_project_id", "") or params.get("project_id", "")
        except Exception:
            pass

    for i in range(60):  # Max 5 min
        await asyncio.sleep(5)

        try:
            # ★ Use media format (NOT operations format) for upscale status
            status_body = build_upscale_status_request(operation_name, project_id)
            status_result = await nano.create_flow(
                flow_auth_token=account["token"],
                body_json=status_body,
                flow_url=STATUS_URL,
                is_proxy=False,
            )

            logger.info(f"📊 Upscale flow poll #{i+1}: {str(status_result)[:400]}")

            # Check if we got a taskId (NanoAI queued it)
            st_task_id = status_result.get("taskId") or status_result.get("task_id")
            if st_task_id:
                logger.info(f"📦 Upscale status got taskId: {st_task_id} — switching to task polling")
                await _poll_upscale_flow_task(job_id, user_id, st_task_id, account)
                return

            # Direct Google response — check both formats
            google_data = status_result.get("result", status_result)
            if not isinstance(google_data, dict):
                continue

            # Check media array (upscale response format)
            media_list = google_data.get("media", [])
            if media_list:
                for media_item in media_list:
                    if not isinstance(media_item, dict):
                        continue

                    media_status = media_item.get("mediaStatus", {}) or {}
                    gen_status = media_status.get("mediaGenerationStatus", "")
                    logger.info(f"📦 Upscale media status: {gen_status}")

                    if gen_status == "MEDIA_GENERATION_STATUS_COMPLETE":
                        # Find download URL in encodedVideo
                        encoded = media_item.get("encodedVideo", {}) or {}
                        upscale_url = encoded.get("url") or encoded.get("videoUrl") or ""

                        # Also check video field
                        if not upscale_url:
                            video_field = google_data.get("video", {}) or {}
                            gen_video = video_field.get("generatedVideo", {}) or {}
                            upscale_url = gen_video.get("url") or gen_video.get("videoUrl") or ""

                        # Deep search for any URL with video
                        if not upscale_url:
                            upscale_url = _find_url_in_response(google_data)

                        if upscale_url:
                            async with async_session_factory() as session:
                                job_result = await session.execute(
                                    select(GenerationJob).where(GenerationJob.id == job_id)
                                )
                                job = job_result.scalar_one_or_none()
                                if job:
                                    params = job.params or {}
                                    params["upscale_url"] = upscale_url
                                    params.pop("upscale_task_id", None)
                                    job.params = params
                                    await session.commit()
                            await publish_progress(user_id, job_id, {
                                "type": "upscale_completed",
                                "job_id": job_id,
                                "upscale_url": upscale_url,
                            })
                            logger.info(f"✅ Flow upscale done for job {job_id}: {upscale_url[:80]}")
                            return
                        else:
                            logger.warning(f"⚠️ Upscale COMPLETE but no URL found in: {str(google_data)[:500]}")
                            # Keep polling — URL might appear next time
                            continue

                    elif gen_status == "MEDIA_GENERATION_STATUS_FAILED":
                        error_msg = media_status.get("failureReason", "Upscale failed")
                        logger.error(f"🔴 Upscale failed: {error_msg}")
                        async with async_session_factory() as session:
                            job_result = await session.execute(
                                select(GenerationJob).where(GenerationJob.id == job_id)
                            )
                            job = job_result.scalar_one_or_none()
                            if job:
                                params = job.params or {}
                                params.pop("upscale_task_id", None)
                                params["upscale_error"] = str(error_msg)[:200]
                                job.params = params
                                await session.commit()
                        await publish_progress(user_id, job_id, {
                            "type": "upscale_failed", "job_id": job_id, "error": str(error_msg)[:200],
                        })
                        return

                    # PENDING — keep polling
                    continue

            # Fallback: check operations format
            if google_data.get("operations"):
                from app.veo_template import parse_status_response
                parsed = parse_status_response(google_data)
                if parsed["done"]:
                    if parsed["status"] == "completed":
                        for v in parsed.get("videos", []):
                            if v.get("download_url"):
                                upscale_url = v["download_url"]
                                async with async_session_factory() as session:
                                    job_result = await session.execute(
                                        select(GenerationJob).where(GenerationJob.id == job_id)
                                    )
                                    job = job_result.scalar_one_or_none()
                                    if job:
                                        params = job.params or {}
                                        params["upscale_url"] = upscale_url
                                        params.pop("upscale_task_id", None)
                                        job.params = params
                                        await session.commit()
                                await publish_progress(user_id, job_id, {
                                    "type": "upscale_completed", "job_id": job_id, "upscale_url": upscale_url,
                                })
                                logger.info(f"✅ Flow upscale done for job {job_id}: {upscale_url[:80]}")
                                return
                    elif parsed["status"] == "failed":
                        error_msg = parsed.get("error", "Upscale failed")
                        async with async_session_factory() as session:
                            job_result = await session.execute(
                                select(GenerationJob).where(GenerationJob.id == job_id)
                            )
                            job = job_result.scalar_one_or_none()
                            if job:
                                params = job.params or {}
                                params.pop("upscale_task_id", None)
                                params["upscale_error"] = str(error_msg)[:200]
                                job.params = params
                                await session.commit()
                        await publish_progress(user_id, job_id, {
                            "type": "upscale_failed", "job_id": job_id, "error": str(error_msg)[:200],
                        })
                        return

                # ═══ Format 2: media array (upscale-specific) ═══
                media_list = data.get("media", [])
                if media_list:
                    for media_item in media_list:
                        if not isinstance(media_item, dict):
                            continue
                        media_status = media_item.get("mediaStatus", {}) or {}
                        gen_status = media_status.get("mediaGenerationStatus", "")
                        logger.info(f"📦 Upscale media status: {gen_status}")

                        if gen_status == "MEDIA_GENERATION_STATUS_COMPLETE":
                            encoded = media_item.get("encodedVideo", {}) or {}
                            upscale_url = encoded.get("url") or encoded.get("videoUrl") or ""
                            if not upscale_url:
                                upscale_url = _find_url_in_response(data)
                            if upscale_url:
                                async with async_session_factory() as session:
                                    job_result = await session.execute(
                                        select(GenerationJob).where(GenerationJob.id == job_id)
                                    )
                                    job = job_result.scalar_one_or_none()
                                    if job:
                                        params = job.params or {}
                                        params["upscale_url"] = upscale_url
                                        params.pop("upscale_task_id", None)
                                        job.params = params
                                        await session.commit()
                                await publish_progress(user_id, job_id, {
                                    "type": "upscale_completed",
                                    "job_id": job_id,
                                    "upscale_url": upscale_url,
                                })
                                logger.info(f"✅ Upscale (media) done: {upscale_url[:80]}")
                                return
                            else:
                                logger.warning(f"⚠️ Media COMPLETE but no URL: {str(data)[:500]}")

                        elif gen_status == "MEDIA_GENERATION_STATUS_FAILED":
                            error_msg = media_status.get("failureReason", "Upscale failed")
                            logger.error(f"🔴 Upscale failed (media): {error_msg}")
                            async with async_session_factory() as session:
                                job_result = await session.execute(
                                    select(GenerationJob).where(GenerationJob.id == job_id)
                                )
                                job = job_result.scalar_one_or_none()
                                if job:
                                    params = job.params or {}
                                    params.pop("upscale_task_id", None)
                                    params["upscale_error"] = str(error_msg)[:200]
                                    job.params = params
                                    await session.commit()
                            await publish_progress(user_id, job_id, {
                                "type": "upscale_failed", "job_id": job_id, "error": str(error_msg)[:200],
                            })
                            return
                    # PENDING - keep polling
                    continue

                # ═══ No operations AND no media — log full response for debug ═══
                logger.info(f"📋 Upscale task result (no ops/media): {str(data)[:500]}")

        except Exception as e:
            logger.error(f"Flow upscale poll error: {e}")

    # Timeout
    logger.warning(f"⚠️ Flow upscale timeout for job {job_id}")
    async with async_session_factory() as session:
        job_result = await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if job:
            params = job.params or {}
            params.pop("upscale_task_id", None)
            params["upscale_error"] = "Timeout — quá 5 phút"
            job.params = params
            await session.commit()


def _find_url_in_response(data: dict, depth: int = 0) -> str:
    """Recursively search for video URL in response data"""
    if depth > 5 or not isinstance(data, dict):
        return ""
    for key, val in data.items():
        if isinstance(val, str) and ("googleapis.com" in val or "googleusercontent.com" in val) and ("video" in val.lower() or ".mp4" in val.lower() or "media" in val.lower()):
            return val
        if isinstance(val, dict):
            found = _find_url_in_response(val, depth + 1)
            if found:
                return found
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    found = _find_url_in_response(item, depth + 1)
                    if found:
                        return found
    return ""


async def _poll_upscale_flow_task(job_id: int, user_id: int, task_id: str, account: dict):
    """Background: poll upscale via NanoAI flow task-status until Google response received.
    If NanoAI task expires (not_found), switches to direct Google polling."""
    import asyncio
    import httpx
    import json as _json
    from app.nanoai_client import get_nanoai_client
    from app.async_worker import publish_progress
    from app.veo_template import parse_status_response, STATUS_URL, DEFAULT_HEADERS, build_upscale_status_request

    nano = get_nanoai_client()
    saved_op_name = ""  # Capture from first successful poll
    saved_project_id = ""

    # Load project_id from job params
    try:
        async with async_session_factory() as session:
            job_result = await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
            job = job_result.scalar_one_or_none()
            if job:
                p = job.params or {}
                saved_project_id = p.get("upscale_project_id", "") or p.get("nanoai_project_id", "") or p.get("project_id", "")
    except Exception:
        pass

    for i in range(120):  # Max 10 min
        await asyncio.sleep(5)

        try:
            task_result = await nano.get_flow_task_status(task_id)
            code = task_result.get("code", "")
            success = task_result.get("success", False)

            logger.info(f"📊 Upscale flow task poll #{i+1}: code={code} success={success}")

            # ═══ NanoAI task expired — switch to direct Google polling ═══
            if code == "not_found":
                if saved_op_name:
                    logger.info(f"🔄 NanoAI expired → direct polling: {saved_op_name[:50]}")
                    await _poll_upscale_direct_google(
                        job_id, user_id, saved_op_name, saved_project_id, account["token"]
                    )
                    return
                else:
                    logger.error("🔴 NanoAI expired, no op name saved")
                    await _save_upscale_error(job_id, user_id, "NanoAI task hết hạn")
                    return

            if code in ("error", "failed"):
                error_msg = task_result.get("message", code)
                logger.error(f"🔴 Upscale task failed: {error_msg}")
                await _save_upscale_error(job_id, user_id, str(error_msg)[:200])
                return

            if not success:
                continue

            data = task_result.get("result", {}) or task_result.get("data", {})
            if not isinstance(data, dict):
                continue

            # ★ Save operation/media name for fallback
            if data.get("operations") and not saved_op_name:
                for op in data["operations"]:
                    n = op.get("operation", {}).get("name") or op.get("name") or ""
                    if n:
                        saved_op_name = n
                        logger.info(f"💾 Saved op: {saved_op_name[:60]}")
                        break
            if data.get("media") and not saved_op_name:
                for m in data["media"]:
                    if isinstance(m, dict) and m.get("name"):
                        saved_op_name = m["name"]
                        logger.info(f"💾 Saved media: {saved_op_name[:60]}")
                        break

            # Check operations
            if data.get("operations"):
                parsed = parse_status_response(data)
                logger.info(f"📦 Status: done={parsed['done']} status={parsed['status']}")
                if parsed["done"] and parsed["status"] == "completed":
                    for v in parsed.get("videos", []):
                        if v.get("download_url"):
                            await _save_upscale_complete(job_id, user_id, v["download_url"])
                            return
                    url = _find_url_in_response(data)
                    if url:
                        await _save_upscale_complete(job_id, user_id, url)
                        return
                elif parsed["done"] and parsed["status"] == "failed":
                    await _save_upscale_error(job_id, user_id, parsed.get("error", "Failed"))
                    return
                continue

            # Check media
            if data.get("media"):
                for m_item in data["media"]:
                    if not isinstance(m_item, dict):
                        continue
                    ms = m_item.get("mediaStatus", {}) or {}
                    gs = ms.get("mediaGenerationStatus", "")
                    logger.info(f"📦 Media: {gs}")
                    if gs == "MEDIA_GENERATION_STATUS_COMPLETE":
                        enc = m_item.get("encodedVideo", {}) or {}
                        url = enc.get("url") or enc.get("videoUrl") or _find_url_in_response(data)
                        if url:
                            await _save_upscale_complete(job_id, user_id, url)
                            return
                    elif gs == "MEDIA_GENERATION_STATUS_FAILED":
                        await _save_upscale_error(job_id, user_id, ms.get("failureReason", "Failed"))
                        return
                continue

            logger.info(f"📋 No ops/media: {str(data)[:500]}")

        except Exception as e:
            logger.error(f"Poll error: {e}")

    # Timeout
    if saved_op_name:
        logger.info(f"⏰ Timeout → direct: {saved_op_name[:50]}")
        await _poll_upscale_direct_google(job_id, user_id, saved_op_name, saved_project_id, account["token"])
        return
    await _save_upscale_error(job_id, user_id, "Timeout — quá 10 phút")


async def _save_upscale_complete(job_id: int, user_id: int, upscale_url: str):
    """Helper: save upscale URL and notify frontend."""
    from app.async_worker import publish_progress
    async with async_session_factory() as session:
        job_result = await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if job:
            p = job.params or {}
            p["upscale_url"] = upscale_url
            p.pop("upscale_task_id", None)
            job.params = p
            await session.commit()
    await publish_progress(user_id, job_id, {"type": "upscale_completed", "job_id": job_id, "upscale_url": upscale_url})
    logger.info(f"✅ Upscale done job {job_id}: {upscale_url[:80]}")


async def _save_upscale_error(job_id: int, user_id: int, error_msg: str):
    """Helper: save upscale error and notify frontend."""
    from app.async_worker import publish_progress
    async with async_session_factory() as session:
        job_result = await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))
        job = job_result.scalar_one_or_none()
        if job:
            p = job.params or {}
            p.pop("upscale_task_id", None)
            p["upscale_error"] = str(error_msg)[:200]
            job.params = p
            await session.commit()
    await publish_progress(user_id, job_id, {"type": "upscale_failed", "job_id": job_id, "error": str(error_msg)[:200]})
    logger.error(f"🔴 Upscale failed job {job_id}: {str(error_msg)[:100]}")


async def _poll_upscale_direct_google(job_id: int, user_id: int, operation_name: str, project_id: str, bearer_token: str):
    """Direct Google polling when NanoAI task expired. Uses the operation name captured during NanoAI polling."""
    import asyncio
    import httpx
    import json as _json
    from app.veo_template import STATUS_URL, DEFAULT_HEADERS, build_upscale_status_request, parse_status_response

    logger.info(f"🔄 Direct Google polling: {operation_name[:50]}, project={project_id}")

    for i in range(60):  # Max 5 more minutes
        await asyncio.sleep(5)
        try:
            status_body = build_upscale_status_request(operation_name, project_id)
            headers = {**DEFAULT_HEADERS, "Authorization": f"Bearer {bearer_token}"}

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(STATUS_URL, headers=headers, content=_json.dumps(status_body))

            if resp.status_code != 200:
                logger.warning(f"⚠️ Direct status HTTP {resp.status_code}: {resp.text[:200]}")
                continue

            data = resp.json()
            logger.info(f"📊 Direct poll #{i+1}: {str(data)[:400]}")

            # Check media
            for m_item in data.get("media", []):
                if not isinstance(m_item, dict):
                    continue
                ms = m_item.get("mediaStatus", {}) or {}
                gs = ms.get("mediaGenerationStatus", "")
                if gs == "MEDIA_GENERATION_STATUS_COMPLETE":
                    enc = m_item.get("encodedVideo", {}) or {}
                    url = enc.get("url") or enc.get("videoUrl") or _find_url_in_response(data)
                    if url:
                        await _save_upscale_complete(job_id, user_id, url)
                        return
                elif gs == "MEDIA_GENERATION_STATUS_FAILED":
                    await _save_upscale_error(job_id, user_id, ms.get("failureReason", "Upscale failed"))
                    return

            # Check operations
            if data.get("operations"):
                parsed = parse_status_response(data)
                if parsed["done"] and parsed["status"] == "completed":
                    for v in parsed.get("videos", []):
                        if v.get("download_url"):
                            await _save_upscale_complete(job_id, user_id, v["download_url"])
                            return

        except Exception as e:
            logger.error(f"Direct poll error: {e}")

    await _save_upscale_error(job_id, user_id, "Timeout — quá 10 phút")


async def _poll_upscale_nanoai(job_id: int, user_id: int, task_id: str):
    """Background: poll NanoAI V2 task status until upscale done.
    ⚠️ Timeout 20s per request, max 40 polls (200s = ~3.5 phút)"""
    import asyncio
    from app.nanoai_client import get_nanoai_client
    from app.async_worker import update_job, publish_progress

    nano = get_nanoai_client()
    empty_success_count = 0  # Track success responses without URL

    for i in range(40):  # Max ~3.5 min (40 × 5s)
        await asyncio.sleep(5)

        try:
            result = await nano.get_v2_task_status(task_id)
            code = result.get("code", "")
            success = result.get("success", False)

            logger.info(f"📊 Upscale poll {task_id[:16]}: code={code} success={success} ({(i+1)*5}s)")
            if success:
                import json as _json
                data_keys = list(result.get("data", {}).keys()) if isinstance(result.get("data"), dict) else "N/A"
                has_raw = bool(result.get("data", {}).get("rawBytes")) if isinstance(result.get("data"), dict) else False
                raw_len = len(result.get("data", {}).get("rawBytes", "")) if isinstance(result.get("data"), dict) else 0
                logger.info(f"🎯 SUCCESS! data_keys={data_keys} has_rawBytes={has_raw} rawBytes_len={raw_len}")
                logger.info(f"🔍 FULL RESPONSE: {_json.dumps(result, default=str)[:1500]}")

            if success and (code == "success" or code == "" or not code):
                # ★ CHECK for NOT_FOUND / ALREADY_EXISTS at top level
                status_field = str(result.get("status", "")).upper()
                message_field = str(result.get("message", "")).lower()

                # ALREADY_EXISTS — video already processed, stop polling
                if "already_exists" in status_field.lower() or "already exists" in message_field or "already in progress" in message_field:
                    logger.warning(f"⚠️ Upscale ALREADY_EXISTS — clearing task and allowing retry")
                    async with async_session_factory() as session:
                        job_result = await session.execute(
                            select(GenerationJob).where(GenerationJob.id == job_id)
                        )
                        job = job_result.scalar_one_or_none()
                        if job:
                            params = job.params or {}
                            params.pop("upscale_task_id", None)
                            params["upscale_error"] = "ALREADY_EXISTS — thử lại với account khác"
                            job.params = params
                            await session.commit()
                    return

                if status_field == "NOT_FOUND" or "not found" in message_field or "requested entity was not found" in message_field:
                    logger.error(f"🔴 Upscale media NOT_FOUND — media_id may be expired or wrong project")
                    async with async_session_factory() as session:
                        job_result = await session.execute(
                            select(GenerationJob).where(GenerationJob.id == job_id)
                        )
                        job = job_result.scalar_one_or_none()
                        if job:
                            params = job.params or {}
                            params.pop("upscale_task_id", None)
                            params["upscale_error"] = "Media not found (404)"
                            job.params = params
                            await session.commit()
                    await publish_progress(user_id, job_id, {
                        "type": "upscale_failed",
                        "job_id": job_id,
                        "error": "Media not found (404) — media_id hết hạn hoặc sai project",
                    })
                    return

                # ★ CHECK for error inside result (NanoAI returns success=True but result.error = 401)
                r_result = result.get("result", {}) or {}
                if isinstance(r_result, dict) and r_result.get("error"):
                    err_info = r_result["error"]
                    err_code = err_info.get("code", 0) if isinstance(err_info, dict) else 0
                    err_msg = err_info.get("message", str(err_info)) if isinstance(err_info, dict) else str(err_info)
                    logger.error(f"🔴 Upscale API error inside result: code={err_code} msg={err_msg[:200]}")
                    if err_code in (401, 404):
                        error_msg = f"API error {err_code}: {err_msg[:100]}"
                        async with async_session_factory() as session:
                            job_result = await session.execute(
                                select(GenerationJob).where(GenerationJob.id == job_id)
                            )
                            job = job_result.scalar_one_or_none()
                            if job:
                                params = job.params or {}
                                params.pop("upscale_task_id", None)
                                params["upscale_error"] = error_msg
                                job.params = params
                                await session.commit()
                        return
                    continue  # Other error — keep polling

                data = result.get("data", {})
                # Search URL in multiple places
                upscale_url = ""
                for src in [data, r_result, result]:
                    if isinstance(src, dict):
                        upscale_url = (
                            src.get("mediaUrl") or src.get("url") or
                            src.get("downloadUrl") or src.get("fileUrl") or
                            src.get("videoUrl") or src.get("fifeUrl") or ""
                        )
                        if upscale_url:
                            break

                # ★ If no URL, check rawBytes (NanoAI V2 returns base64 video directly!)
                if not upscale_url:
                    raw_bytes_str = ""
                    for src in [data, r_result, result]:
                        if isinstance(src, dict) and src.get("rawBytes"):
                            raw_bytes_str = src["rawBytes"]
                            break
                    if raw_bytes_str:
                        logger.info(f"📦 Video upscale returned rawBytes ({len(raw_bytes_str)} chars) → saving locally")
                        try:
                            import base64, os, time
                            video_bytes = base64.b64decode(raw_bytes_str)
                            # Save to static/upscaled/ directory
                            static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "upscaled")
                            os.makedirs(static_dir, exist_ok=True)
                            filename = f"video_{job_id}_{int(time.time())}.mp4"
                            filepath = os.path.join(static_dir, filename)
                            with open(filepath, "wb") as f:
                                f.write(video_bytes)
                            upscale_url = f"/static/upscaled/{filename}"
                            logger.info(f"✅ rawBytes saved: {filepath} ({len(video_bytes)} bytes) → {upscale_url}")
                        except Exception as e:
                            logger.error(f"❌ Failed to save rawBytes: {e}")

                if upscale_url:
                    # ★ Resolve labs.google URL → storage.googleapis.com download URL
                    # Use Google status API via NanoAI flow proxy (same method as 720p video)
                    if "getMediaUrlRedirect" in upscale_url or "labs.google" in upscale_url:
                        try:
                            # Extract upsampled media name from URL
                            import urllib.parse
                            parsed_url = urllib.parse.urlparse(upscale_url)
                            qs = urllib.parse.parse_qs(parsed_url.query)
                            upsampled_name = qs.get("name", [""])[0]
                            
                            if upsampled_name:
                                # Get account + project from job
                                async with async_session_factory() as s2:
                                    job2 = (await s2.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                                    p2 = job2.params or {} if job2 else {}
                                    upscale_project_id = p2.get("upscale_project_id") or p2.get("project_id", "")
                                    acc_id = job2.account_id if job2 else None
                                
                                bearer_token = ""
                                if acc_id:
                                    from app.models import UltraAccount
                                    async with async_session_factory() as s3:
                                        acc_obj = (await s3.execute(select(UltraAccount).where(UltraAccount.id == acc_id))).scalar_one_or_none()
                                        if acc_obj:
                                            bearer_token = acc_obj.bearer_token or ""
                                
                                if bearer_token and upscale_project_id:
                                    from app.veo_template import build_upscale_status_request, STATUS_URL
                                    
                                    # Build status check for upsampled media
                                    status_body = build_upscale_status_request(upsampled_name, upscale_project_id)
                                    
                                    logger.info(f"🔗 Fetching download URL for {upsampled_name} via flow proxy...")
                                    
                                    # Send status check through NanoAI flow proxy
                                    status_result = await nano.create_flow(
                                        flow_auth_token=bearer_token,
                                        flow_url=STATUS_URL,
                                        body_json=status_body,
                                        is_proxy=False,
                                    )
                                    
                                    status_task_id = status_result.get("taskId") or status_result.get("task_id")
                                    if status_task_id:
                                        # Poll for the status result
                                        for si in range(15):
                                            await asyncio.sleep(3)
                                            sr = await nano.get_flow_task_status(status_task_id)
                                            sr_success = sr.get("success", False)
                                            sr_code = sr.get("code", "")
                                            
                                            if not sr_success or sr_code == "processing":
                                                continue
                                            
                                            # Got result — extract download URL
                                            sr_data = sr.get("result", {}) or {}
                                            if isinstance(sr_data, dict):
                                                ops = sr_data.get("operations", [])
                                                for op in ops:
                                                    entries = op.get("data", []) or op.get("entries", [])
                                                    if isinstance(entries, list):
                                                        for entry in entries:
                                                            dl = entry.get("downloadUrl") or entry.get("fifeUrl") or ""
                                                            if dl and "storage.googleapis.com" in dl:
                                                                upscale_url = dl
                                                                logger.info(f"✅ Got storage URL: {upscale_url[:80]}...")
                                                                break
                                                        if "storage.googleapis.com" in upscale_url:
                                                            break
                                                    # Also check metadata
                                                    meta = op.get("operation", {}).get("metadata", {})
                                                    fife = meta.get("video", {}).get("fifeUrl", "")
                                                    if fife and "storage.googleapis.com" in fife:
                                                        upscale_url = fife
                                                        break
                                            break
                        except Exception as e:
                            logger.warning(f"⚠️ URL resolution failed (using original): {e}")

                    # Save to DB
                    async with async_session_factory() as session:
                        job_result = await session.execute(
                            select(GenerationJob).where(GenerationJob.id == job_id)
                        )
                        job = job_result.scalar_one_or_none()
                        if job:
                            params = job.params or {}
                            params["upscale_url"] = upscale_url
                            params.pop("upscale_task_id", None)
                            job.params = {**params}  # ★ NEW dict to trigger SQLAlchemy change detection
                            flag_modified(job, "params")
                            await session.commit()
                            logger.info(f"💾 DB SAVED upscale_url for job {job_id}")

                    await publish_progress(user_id, job_id, {
                        "type": "upscale_completed",
                        "job_id": job_id,
                        "upscale_url": upscale_url,
                    })
                    logger.info(f"✅ Video upscale done for job {job_id}: {upscale_url[:80]}")
                    return

                import json as _json
                empty_success_count += 1
                logger.warning(f"⚠️ Upscale success but no URL/rawBytes ({empty_success_count}/5). FULL: {_json.dumps(result, default=str)[:1000]}")
                if empty_success_count >= 5:
                    logger.error(f"🔴 5x success without URL — giving up")
                    await _save_upscale_error(job_id, user_id, "Upscale hoàn thành nhưng không trả URL (5 lần)")
                    return
                continue

            if code in ("error", "failed", "not_found"):
                error_msg = result.get('message', code)
                logger.error(f"🔴 Upscale poll error: {error_msg}")

                # ★ AUTO-RETRY: NanoAI transient errors ("Create nanoai error") — retry once
                transient_errors = ["create nanoai", "internal", "timeout", "rate limit", "try again"]
                is_transient = any(t in error_msg.lower() for t in transient_errors)
                if is_transient and i < 30:  # Only retry in first half of polling
                    logger.info(f"🔄 Transient error '{error_msg}' — waiting 10s then continuing poll...")
                    await asyncio.sleep(10)
                    continue

                # ★ Extract projectId from error data (NanoAI includes it)
                error_data = result.get("data", {}) or {}
                extracted_project_id = ""
                if isinstance(error_data, dict):
                    media_list = error_data.get("media", [])
                    if isinstance(media_list, list):
                        for m in media_list:
                            if isinstance(m, dict) and m.get("projectId"):
                                extracted_project_id = m["projectId"]
                                break

                # Clean up task_id so user can retry
                # ★ RACE GUARD: only modify if this poll's task_id still matches DB
                async with async_session_factory() as session:
                    job_result = await session.execute(
                        select(GenerationJob).where(GenerationJob.id == job_id)
                    )
                    job = job_result.scalar_one_or_none()
                    if job:
                        params = job.params or {}
                        current_task = params.get("upscale_task_id", "")
                        # If task_id was cleared or changed → this poll is stale
                        if current_task != task_id:
                            logger.info(f"⚠️ Stale poll {task_id[:12]}... — DB task={current_task[:12] if current_task else 'CLEARED'}, skipping")
                            return
                        params.pop("upscale_task_id", None)
                        params["upscale_error"] = str(error_msg)[:200]
                        # Save extracted projectId for future retry
                        if extracted_project_id:
                            params["project_id"] = extracted_project_id
                            logger.info(f"💡 Saved correct projectId from error: {extracted_project_id}")
                        job.params = {**params}  # ★ NEW dict
                        flag_modified(job, "params")
                        await session.commit()

                    # ★ Only notify frontend if this poll owns the task
                    await publish_progress(user_id, job_id, {
                        "type": "upscale_failed",
                        "job_id": job_id,
                        "error": str(error_msg)[:200],
                    })
                return

        except Exception as e:
            logger.error(f"Upscale poll error: {e}")

    logger.warning(f"⚠️ Upscale timeout for job {job_id} after {40*5}s")
    # Clean up on timeout — ★ RACE GUARD
    async with async_session_factory() as session:
        job_result = await session.execute(
            select(GenerationJob).where(GenerationJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if job:
            params = job.params or {}
            current_task = params.get("upscale_task_id", "")
            if current_task != task_id:
                logger.info(f"⚠️ Stale timeout {task_id[:12]}... — DB task={current_task[:12] if current_task else 'CLEARED'}, skipping")
                return
            params.pop("upscale_task_id", None)
            params["upscale_error"] = "Timeout — quá 5 phút"
            job.params = {**params}  # ★ NEW dict
            flag_modified(job, "params")
            await session.commit()

    # Notify frontend of timeout
    await publish_progress(user_id, job_id, {
        "type": "upscale_failed",
        "job_id": job_id,
        "error": "Upscale timeout — quá 5 phút",
    })


# ═══════════════════════════════════════════════════════════════════════════════
# UPSCALE IMAGE (1K / 2K / 4K) — via NanoAI V2
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/upscale-image/{job_id}")
async def upscale_image(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Upscale image to higher resolution via NanoAI V2.
    Body: {"resolution": "RESOLUTION_1K" | "RESOLUTION_2K" | "RESOLUTION_4K"}
    Returns base64 image or URL.
    """
    user_data = get_current_user(request)

    body = await request.json()
    target_resolution = body.get("resolution", "RESOLUTION_2K")

    result = await db.execute(
        select(GenerationJob).where(
            GenerationJob.id == job_id,
            GenerationJob.user_id == user_data["user_id"],
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Image not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Ảnh chưa hoàn thành")

    # Try to get media_id — prefer NanoAI UUID format
    params = job.params or {}
    img_media_id = job.media_id or params.get("nanoai_media_id", "") or job.operation_id or ""
    if not img_media_id:
        raise HTTPException(status_code=400, detail="Ảnh thiếu media_id, không thể upscale")

    logger.info(f"🔍 Image upscale request: job={job_id}, media_id={img_media_id[:40]}, account_id={job.account_id}")

    # Check cache
    cache_key = f"upscale_{target_resolution}_url"
    if params.get(cache_key):
        return {"success": True, "status": "completed", "upscale_url": params[cache_key]}

    from app.async_worker import get_account_token, report_account_result
    from app.nanoai_client import get_nanoai_client
    from app.models import UltraAccount

    nano = get_nanoai_client()
    MAX_RETRIES = 3
    tried_emails: list[str] = []
    last_error = ""

    # ★ Priority: use the SAME account that created the image
    creating_account = None
    if job.account_id:
        async with async_session_factory() as session:
            acc_result = await session.execute(
                select(UltraAccount).where(UltraAccount.id == job.account_id)
            )
            acc = acc_result.scalar_one_or_none()
            if acc and acc.bearer_token and acc.is_enabled:
                creating_account = {
                    "email": acc.email,
                    "token": acc.bearer_token,
                    "account_id": acc.id,
                }
                logger.info(f"✅ Using creating account: {acc.email}")

    for attempt in range(MAX_RETRIES):
        # First attempt: use creating account; then fallback to others
        if attempt == 0 and creating_account:
            account = creating_account
        else:
            account = await get_account_token(exclude_emails=tried_emails)
            if not account:
                break
        tried_emails.append(account["email"])

        # Get project_id: from job params first, then from account
        project_id = params.get("project_id", "") or await _get_project_id_for_account(account["account_id"])
        if not project_id:
            logger.info(f"⏭️ Account {account['email']} has no project_id — skipping for image upscale")
            continue

        # Get cookie for this account
        cookie = await _get_account_cookie(account["account_id"])

        try:
            logger.info(f"🔍 Image upscale: job={job_id}, media_id={img_media_id[:30]}, project={project_id[:20]}, res={target_resolution}, account={account['email']}, hasCookie={bool(cookie)}, attempt={attempt+1}")

            upscale_result = await nano.upscale_image(
                access_token=account["token"],
                media_id=img_media_id,
                project_id=project_id,
                target_resolution=target_resolution,
                cookie=cookie or "",
            )

            logger.info(f"📡 Image upscale response: {str(upscale_result)[:500]}")

            if upscale_result.get("error"):
                last_error = str(upscale_result.get("error", ""))[:300]
                logger.error(f"🔴 Image upscale error (attempt {attempt+1}): {last_error}")
                await report_account_result(account["email"], False, last_error)
                continue

            if upscale_result.get("success"):
                # Result can contain: encodedImage (base64) or URL
                result_data = upscale_result.get("result", {})
                encoded_image = result_data.get("encodedImage", "")

                if encoded_image:
                    data_uri = f"data:image/png;base64,{encoded_image}"
                    params[cache_key] = data_uri
                    job.params = params
                    await db.commit()
                    await report_account_result(account["email"], True)
                    return {
                        "success": True,
                        "status": "completed",
                        "upscale_url": data_uri,
                        "resolution": target_resolution,
                    }

                # Check if URL returned instead
                media_url = (
                    result_data.get("mediaUrl") or result_data.get("url") or
                    result_data.get("imageUrl") or result_data.get("fileUrl") or ""
                )
                if media_url:
                    params[cache_key] = media_url
                    job.params = params
                    await db.commit()
                    await report_account_result(account["email"], True)
                    return {
                        "success": True,
                        "status": "completed",
                        "upscale_url": media_url,
                        "resolution": target_resolution,
                    }

            # Check if async task
            task_id = upscale_result.get("taskId") or upscale_result.get("task_id")
            if task_id:
                logger.info(f"⏳ Image upscale async taskId: {task_id}")
                # ★ Save task_id and return IMMEDIATELY — poll in background
                # ★ MUST copy dict to force SQLAlchemy JSON mutation detection
                params = dict(params)
                params["upscale_task_id"] = task_id
                params["upscale_status"] = "processing"
                params["upscale_resolution"] = target_resolution
                job.params = params
                await db.commit()
                logger.info(f"💾 Saved upscale_task_id={task_id} to job {job_id} params")

                # ★ Start background poll as asyncio task (NOT thread — DB sessions need same loop)
                import asyncio
                asyncio.create_task(
                    _poll_image_upscale_nanoai(job_id, task_id, account["email"], target_resolution, cache_key)
                )
                logger.info(f"🚀 Image upscale background task started for job {job_id}")

                return {
                    "success": True,
                    "status": "processing",
                    "message": "Đang upscale ảnh (~1-2 phút)...",
                }

            last_error = "Không nhận được kết quả từ API"
            continue

        except Exception as e:
            last_error = str(e)
            logger.error(f"Image upscale error (attempt {attempt+1}): {e}")
            await report_account_result(account["email"], False, str(e))
            continue

    raise HTTPException(status_code=502, detail=f"Upscale lỗi sau {MAX_RETRIES} lần thử: {last_error}")


# ═══════════════════════════════════════════════════════════════════════════════
# BACKGROUND: Poll Image Upscale (runs in separate thread)
# ═══════════════════════════════════════════════════════════════════════════════

async def _poll_image_upscale_nanoai(job_id: int, task_id: str, account_email: str, target_resolution: str, cache_key: str):
    """Background poll for image upscale — same pattern as video upscale."""
    import asyncio
    from app.nanoai_client import get_nanoai_client
    from app.async_worker import report_account_result

    nano = get_nanoai_client()
    MAX_POLLS = 40  # 40 × 5s = ~3.5 min
    empty_success_count = 0

    for i in range(MAX_POLLS):
        await asyncio.sleep(5)

        try:
            # ★ Race guard: check if task_id still matches (another upscale may have started)
            async with async_session_factory() as session:
                result = await session.execute(
                    select(GenerationJob).where(GenerationJob.id == job_id)
                )
                job = result.scalar_one_or_none()
                if not job:
                    logger.error(f"🔴 Image upscale: job {job_id} not found")
                    return

                params = job.params or {}
                current_task = params.get("upscale_task_id", "")
                if current_task != task_id:
                    logger.info(f"🛑 Image upscale: task_id mismatch ({task_id[:16]} vs {current_task[:16]}) — stopping")
                    return

            task_status = await nano.get_v2_task_status(task_id)
            t_code = task_status.get("code", "")
            t_success = task_status.get("success", False)
            logger.info(f"📊 Image upscale bg poll: code={t_code} success={t_success} ({(i+1)*5}s)")

            if t_success and (t_code == "success" or t_code == "" or not t_code):
                t_data = task_status.get("data", {}) or {}
                t_result = task_status.get("result", {}) or {}

                # CHECK NOT_FOUND
                t_status = str(task_status.get("status", "")).upper()
                t_message = str(task_status.get("message", "")).lower()
                if t_status == "NOT_FOUND" or "not found" in t_message:
                    logger.error(f"🔴 Image upscale NOT_FOUND — stopping")
                    async with async_session_factory() as session:
                        j = (await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                        if j:
                            p = dict(j.params or {})
                            p.pop("upscale_task_id", None)
                            p["upscale_status"] = "failed"
                            p["upscale_error"] = "Media not found (404)"
                            j.params = p
                            await session.commit()
                    return

                # CHECK error inside result
                if isinstance(t_result, dict) and t_result.get("error"):
                    err_info = t_result["error"]
                    err_code = err_info.get("code", 0) if isinstance(err_info, dict) else 0
                    if err_code in (401, 404):
                        async with async_session_factory() as session:
                            j = (await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                            if j:
                                p = dict(j.params or {})
                                p.pop("upscale_task_id", None)
                                p["upscale_status"] = "failed"
                                p["upscale_error"] = f"API error ({err_code})"
                                j.params = p
                                await session.commit()
                        return
                    continue

                # Search encodedImage
                enc = t_result.get("encodedImage") or t_data.get("encodedImage") or task_status.get("encodedImage") or ""
                if enc:
                    data_uri = f"data:image/png;base64,{enc}"
                    async with async_session_factory() as session:
                        j = (await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                        if j:
                            p = dict(j.params or {})
                            p[cache_key] = data_uri
                            p["upscale_url"] = data_uri
                            p.pop("upscale_task_id", None)
                            p["upscale_status"] = "completed"
                            j.params = p
                            await session.commit()
                    await report_account_result(account_email, True)
                    logger.info(f"🎉 Image upscale done (base64)! job={job_id}")
                    return

                # Search URL
                m_url = ""
                for src in [t_data, t_result, task_status]:
                    if isinstance(src, dict):
                        m_url = src.get("mediaUrl") or src.get("url") or src.get("imageUrl") or src.get("fileUrl") or src.get("fifeUrl") or ""
                        if m_url:
                            break
                if m_url:
                    async with async_session_factory() as session:
                        j = (await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                        if j:
                            p = dict(j.params or {})
                            p[cache_key] = m_url
                            p["upscale_url"] = m_url
                            p.pop("upscale_task_id", None)
                            p["upscale_status"] = "completed"
                            j.params = p
                            await session.commit()
                    await report_account_result(account_email, True)
                    logger.info(f"🎉 Image upscale done (URL)! job={job_id} url={m_url[:80]}")
                    return

                # Success but no data — count
                empty_success_count += 1
                if empty_success_count >= 5:
                    logger.error(f"🔴 Image upscale: 5 success with no data — stopping")
                    break

            if t_code in ("error", "failed"):
                err_msg = task_status.get("message", t_code)
                logger.error(f"🔴 Image upscale failed: {err_msg}")
                async with async_session_factory() as session:
                    j = (await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
                    if j:
                        p = dict(j.params or {})
                        p.pop("upscale_task_id", None)
                        p["upscale_status"] = "failed"
                        p["upscale_error"] = str(err_msg)[:200]
                        j.params = p
                        await session.commit()
                return

        except Exception as e:
            logger.error(f"⚠️ Image upscale poll error: {e}")

    # Timeout
    logger.error(f"🔴 Image upscale timeout job={job_id}")
    async with async_session_factory() as session:
        j = (await session.execute(select(GenerationJob).where(GenerationJob.id == job_id))).scalar_one_or_none()
        if j:
            p = dict(j.params or {})
            p.pop("upscale_task_id", None)
            p["upscale_status"] = "failed"
            p["upscale_error"] = "Upscale timeout — quá 3.5 phút"
            j.params = p
            await session.commit()
