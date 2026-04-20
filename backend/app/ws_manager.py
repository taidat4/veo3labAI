"""
WebSocket Manager — Realtime progress updates
Sử dụng Redis pub/sub để nhận events từ Celery worker
rồi push cho WebSocket clients.
"""

import asyncio
import json
import logging
from typing import Dict, Set

from fastapi import WebSocket, WebSocketDisconnect
try:
    from redis.asyncio import Redis as AsyncRedis
except ImportError:
    AsyncRedis = None

logger = logging.getLogger("veo3.ws")

# Channel Redis pub/sub (worker publish, ws subscribe)
PROGRESS_CHANNEL = "veo3:progress"


class WSConnectionManager:
    """
    Quản lý WebSocket connections.
    Mỗi user có 1 room, nhận progress events cho jobs của mình.
    """

    def __init__(self):
        # user_id → set of websocket connections
        self._connections: Dict[int, Set[WebSocket]] = {}
        self._pubsub_task: asyncio.Task | None = None
        self._running = False

    async def connect(self, websocket: WebSocket, user_id: int):
        """Accept connection và thêm vào room"""
        await websocket.accept()
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(websocket)
        logger.info(f"🔗 WS connected: user={user_id} (total={len(self._connections[user_id])})")

    async def disconnect(self, websocket: WebSocket, user_id: int):
        """Remove connection khỏi room"""
        if user_id in self._connections:
            self._connections[user_id].discard(websocket)
            if not self._connections[user_id]:
                del self._connections[user_id]
        logger.info(f"🔌 WS disconnected: user={user_id}")

    async def send_to_user(self, user_id: int, data: dict):
        """Push event cho tất cả connections của 1 user"""
        if user_id not in self._connections:
            return

        dead = set()
        for ws in self._connections[user_id]:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)

        # Cleanup dead connections
        for ws in dead:
            self._connections[user_id].discard(ws)

    async def broadcast(self, data: dict):
        """Push event cho tất cả users"""
        for user_id in list(self._connections.keys()):
            await self.send_to_user(user_id, data)

    async def start_pubsub_listener(self, redis: AsyncRedis):
        """Subscribe Redis pub/sub → forward events cho WebSocket clients"""
        if self._running:
            return
        self._running = True
        self._pubsub_task = asyncio.create_task(self._listen_redis(redis))
        logger.info("📡 WebSocket PubSub listener started")

    async def stop_pubsub_listener(self):
        """Dừng listener"""
        self._running = False
        if self._pubsub_task:
            self._pubsub_task.cancel()

    async def _listen_redis(self, redis: AsyncRedis):
        """Main loop: subscribe Redis channel → forward cho WS"""
        pubsub = redis.pubsub()
        await pubsub.subscribe(PROGRESS_CHANNEL)

        try:
            while self._running:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        user_id = data.get("user_id")
                        if user_id is not None:
                            await self.send_to_user(int(user_id), data)
                    except Exception as e:
                        logger.error(f"❌ PubSub parse error: {e}")
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(PROGRESS_CHANNEL)
            await pubsub.close()

    @property
    def active_connections_count(self) -> int:
        return sum(len(conns) for conns in self._connections.values())

    @property
    def active_users_count(self) -> int:
        return len(self._connections)


# Singleton
ws_manager = WSConnectionManager()
