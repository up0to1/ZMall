"""
WebSocket 端点（AI 模特图专属）

U1 统一架构后 ai-models 仅承载 AI 模特图的 WS 推送：
  - 路径：/ws/model/{userId}
  - 推送方：app/mq/model_consumer.py（消费 ai.model.generate 队列后推送结果）
  - 消息 type：AI_MODEL

AI 随心搭的 WS 推送已迁移到 ai-outfit：
  - 路径：/ws/ai/{userId}（Gateway 路由到 ai-outfit）
  - 消息 type：OUTFIT_PRODUCT / OUTFIT_AGENT

按 userId 建连，支持多页面。

增加鉴权（user-info header 或首条 auth 消息）+ 连接数限制。
F8 修复：token 从 URL query 迁移到首条消息认证，避免 token 泄露在 access log。
"""
import asyncio
import base64
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from shared.ws_manager import WebSocketManager

logger = logging.getLogger(__name__)
router = APIRouter()

# AI 模特图 WebSocket 管理器单例（仅 ai-models 内部使用）
ws_manager = WebSocketManager()

# 同一 userId 最大连接数限制
MAX_CONNECTIONS_PER_USER = 10

# F8: 首条 auth 消息等待超时（秒）
AUTH_TIMEOUT_SECONDS = 5


def _is_valid_jwt_format(token: str) -> bool:
    """校验 token 是否为 JWT 格式（三段式 header.payload.signature）

    仅校验格式，不验证签名（签名验证由 Gateway 完成）。
    防止 token=1 等任意字符串通过鉴权。
    """
    if not token or len(token) < 16:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    return all(parts)


def _extract_jwt_user_id(token: str) -> str | None:
    """从 JWT payload 中提取 userId（不验证签名，签名由 Gateway 校验）

    用于 WS 兜底鉴权：当 Gateway 未设置 user-info header 时，
    从首条 auth 消息的 token 中解码 userId 并与路径 userId 比较，防 IDOR。
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # base64url 解码 payload（第二段），补齐 padding
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        # JwtTool 中 payload 字段名为 "user"
        user = payload.get("user")
        return str(user) if user is not None else None
    except Exception:
        return None


def _verify_ws_token(token: str, path_user_id: str) -> bool:
    """F8: 校验首条 auth 消息中的 token

    校验 JWT 格式 + userId 匹配（签名验证由 Gateway 完成，Python 侧防任意字符串）。
    """
    if not _is_valid_jwt_format(token):
        return False
    token_user_id = _extract_jwt_user_id(token)
    if token_user_id and token_user_id == path_user_id:
        return True
    logger.warning("WS 鉴权失败：token userId 与路径 userId 不匹配: token_user=%s, path=%s",
                   token_user_id, path_user_id)
    return False


@router.websocket("/ws/model/{user_id}")
async def model_progress(websocket: WebSocket, user_id: str):
    """AI 模特图任务进度 WebSocket 推送

    鉴权策略（按优先级）：
    1. Gateway 透传的 user-info header → 校验与路径 userId 是否匹配，直接通过
    2. 首条 auth 消息认证 → accept 后等待 {"type":"auth","token":"xxx"}，校验 JWT userId
    3. 超时或鉴权失败 → 关闭连接
    """
    # 方式1：Gateway 透传 user-info header（正常流程，无需 token）
    user_info = websocket.headers.get("user-info")
    if user_info:
        if user_info != user_id:
            logger.warning("WS 鉴权失败：user-info header 与路径 userId 不匹配: header=%s, path=%s",
                           user_info, user_id)
            await websocket.close(code=4001, reason="鉴权失败")
            return
        authenticated = True
    else:
        # 方式2：F8 修复 - 首条消息认证
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS
            )
            msg = json.loads(raw)
            if msg.get("type") != "auth" or not _verify_ws_token(msg.get("token", ""), user_id):
                logger.warning("WS 鉴权失败：auth 消息无效: path=%s", user_id)
                await websocket.send_text(json.dumps({"type": "auth_fail"}))
                await websocket.close(code=4001, reason="鉴权失败")
                return
            await websocket.send_text(json.dumps({"type": "auth_ok"}))
        except asyncio.TimeoutError:
            logger.warning("WS 鉴权超时：未收到 auth 消息: path=%s", user_id)
            await websocket.close(code=4001, reason="鉴权超时")
            return
        except Exception as e:
            logger.warning("WS 鉴权异常: path=%s, error=%s", user_id, e)
            await websocket.close(code=4001, reason="鉴权失败")
            return
        authenticated = True

    if not authenticated:
        return

    # 连接数限制
    conns = ws_manager._connections.get(user_id, set())
    if len(conns) >= MAX_CONNECTIONS_PER_USER:
        logger.warning("WS 连接数超限: userId=%s, current=%d, max=%d",
                       user_id, len(conns), MAX_CONNECTIONS_PER_USER)
        await websocket.close(code=4002, reason="连接数超限")
        return

    # 加入连接池
    if user_info:
        # user-info header 方式尚未 accept
        await ws_manager.connect(user_id, websocket)
    else:
        # 首条消息方式已 accept，直接加入连接池
        ws_manager._connections[user_id].add(websocket)
        logger.info("WebSocket 已连接: userId=%s, 当前连接数=%d", user_id, len(ws_manager._connections[user_id]))

    logger.info("WS 连接建立: userId=%s, current_conns=%d", user_id, len(conns) + 1)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(user_id, websocket)
    except Exception as e:
        logger.warning("WebSocket 异常: userId=%s, error=%s", user_id, e)
        ws_manager.disconnect(user_id, websocket)
