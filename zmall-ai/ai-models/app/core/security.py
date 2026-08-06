"""
认证中间件

Gateway 解析 JWT 后将 userId 放入 `user-info` 请求头，
本中间件解析该头部，注入到 request.state.user_id。

安全策略：
- 公开路径（/health /docs 等）直接放行
- WebSocket 升级请求由端点自行处理 user_id
- 其他路径未携带 user-info 头部 → 返回 401（防止绕过 Gateway 直连服务
  调用付费接口消耗配额，如多 Agent 工作流每次消耗 VTON + Vision LLM 费用）
"""
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# 不需要鉴权的路径
PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/metrics"}


class AuthMiddleware(BaseHTTPMiddleware):
    """解析 user-info 请求头，注入用户身份"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 公开路径直接放行
        if path in PUBLIC_PATHS or path.startswith("/docs"):
            return await call_next(request)

        # WebSocket 升级请求由端点自行处理 user_id
        if path.startswith("/ws/"):
            return await call_next(request)

        # 从 Gateway 透传的 user-info 头部获取 userId
        user_info = request.headers.get("user-info")
        if user_info:
            try:
                request.state.user_id = int(user_info)
            except ValueError:
                logger.warning("user-info 头部格式非法: path=%s, value=%s",
                               path, user_info[:50])
                return JSONResponse(
                    status_code=401,
                    content={"detail": "invalid user-info header"},
                )
        else:
            # 未携带 user-info 的非公开路径直接拒绝
            # 防止绕过 Gateway 直连服务调用付费接口消耗配额
            logger.warning("请求未携带 user-info 头部已拒绝: path=%s, ip=%s",
                           path, request.client.host if request.client else "unknown")
            return JSONResponse(
                status_code=401,
                content={"detail": "missing user-info header"},
            )

        # 从 Gateway 透传的 user-role 头部获取角色
        user_role = request.headers.get("user-role")
        if user_role:
            try:
                request.state.user_role = int(user_role)
            except ValueError:
                request.state.user_role = None
        else:
            request.state.user_role = None

        return await call_next(request)
