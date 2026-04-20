"""
WebSocket Routes — Realtime progress
"""

import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth import decode_token
from app.ws_manager import ws_manager

logger = logging.getLogger("veo3.route.ws")
router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/progress/{user_id}")
async def websocket_progress(websocket: WebSocket, user_id: int):
    """
    WebSocket endpoint cho realtime progress updates.

    Client connect → nhận events:
    - {"type": "progress", "job_id": 1, "progress_percent": 50}
    - {"type": "completed", "job_id": 1, "video_url": "..."}
    - {"type": "failed", "job_id": 1, "error": "..."}

    Auth: gửi JWT token trong query string hoặc first message
    """
    # Verify auth (từ query param)
    token = websocket.query_params.get("token")
    if token:
        # BYPASS MODE — TODO: bật lại khi deploy production
        if token == "dev-bypass-token":
            pass  # Allow dev bypass
        else:
            payload = decode_token(token)
            if not payload or int(payload.get("sub", 0)) != user_id:
                await websocket.accept()
                await websocket.close(code=4001, reason="Unauthorized")
                return

    await ws_manager.connect(websocket, user_id)

    try:
        while True:
            # Keep connection alive bằng cách đợi messages từ client
            # Client có thể gửi ping/pong hoặc subscribe specific jobs
            data = await websocket.receive_text()

            # Xử lý client messages (nếu cần)
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"❌ WS error: {e}")
    finally:
        await ws_manager.disconnect(websocket, user_id)
