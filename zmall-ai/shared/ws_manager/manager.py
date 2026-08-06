"""
WebSocket 连接池管理器

按 userId 维护连接池，支持同一用户多页面多连接。
ai-models 和 ai-outfit 各自维护独立的 WebSocketManager 实例（两个进程不共享内存）。

迭代安全性：
  send_to_user / broadcast 在迭代连接集合时调用 await ws.send_text，
  期间会 yield 控制权给事件循环，其他协程可能同时调用 disconnect 修改 set。
  因此迭代前用 list() 做快照，避免 "Set changed size during iteration"。
"""
import json
import logging
from collections import defaultdict
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """按 userId 维护 WebSocket 连接池"""

    def __init__(self):
        # user_id -> set[WebSocket]，同一用户可能开多页面
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: str, websocket: WebSocket):
        """接受连接并加入连接池"""
        await websocket.accept()
        self._connections[user_id].add(websocket)
        logger.info("WebSocket 已连接: userId=%s, 当前连接数=%d", user_id, len(self._connections[user_id]))

    def disconnect(self, user_id: str, websocket: WebSocket):
        """从连接池移除连接"""
        conns = self._connections.get(user_id)
        if conns:
            conns.discard(websocket)
            if not conns:
                del self._connections[user_id]
        logger.info("WebSocket 已断开: userId=%s", user_id)

    async def send_to_user(self, user_id: str, message: dict):
        """向指定用户的所有连接推送消息（支持多页面）

        迭代前用 list() 做快照，避免迭代期间 disconnect 修改 set 抛 RuntimeError。
        """
        conns = self._connections.get(user_id)
        if not conns:
            logger.debug("用户 %s 无活跃 WS 连接，跳过推送", user_id)
            return
        text = json.dumps(message, ensure_ascii=False)
        dead: list[WebSocket] = []
        # 快照迭代：避免 await 期间 set 被并发修改
        for ws in list(conns):
            try:
                await ws.send_text(text)
            except Exception as e:
                logger.warning("WS 推送失败: userId=%s, error=%s", user_id, e)
                dead.append(ws)
        # 清理断开的连接
        for ws in dead:
            conns.discard(ws)
        if not conns:
            del self._connections[user_id]

    async def broadcast(self, message: dict):
        """向所有在线用户的所有连接广播消息（如系统公告、全局通知）

        与 send_to_user 同样使用 list() 快照迭代，避免并发 disconnect 修改 set。
        """
        text = json.dumps(message, ensure_ascii=False)
        dead: list[tuple[str, WebSocket]] = []
        for user_id, conns in list(self._connections.items()):
            for ws in list(conns):
                try:
                    await ws.send_text(text)
                except Exception as e:
                    logger.warning("WS broadcast 失败: userId=%s, error=%s", user_id, e)
                    dead.append((user_id, ws))
        # 清理断开的连接
        for user_id, ws in dead:
            conns = self._connections.get(user_id)
            if conns:
                conns.discard(ws)
                if not conns:
                    del self._connections[user_id]
