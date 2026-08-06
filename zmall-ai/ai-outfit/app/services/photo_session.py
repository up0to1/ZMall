"""
照片会话管理（U1 统一架构：从 ai-models 迁移到 ai-outfit）

用户真人照片持久化策略：
  - 上传时同步把照片 bytes 上传到 OSS（或本地降级存储），拿到 URL 存 Redis
  - Redis 仍缓存 base64 字符串供节点1 节点4 VTON 输入使用（TTL 30min）
  - accept 入库时从 Redis 读 URL → 传给 Java 入 ai_outfit_record.user_photo_url + user_wardrobe.original_photo_url
  - 两个 Redis Key：
    · ai:photo:session:{userId}:{sessionId}        → base64 字符串（VTON 输入用）
    · ai:photo:session:url:{userId}:{sessionId}    → OSS URL（accept 入库用）

photoSessionKey 为 {userId}:{sessionId}，同一用户多设备上传照片互不覆盖。
clear_photo 用 SCAN 清除该用户所有设备会话。
"""
import asyncio
import base64
import hashlib
import logging
import uuid
from datetime import datetime
from pathlib import Path

import redis.asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

PHOTO_SESSION_TTL = 1800  # 30 分钟
PHOTO_SESSION_PREFIX = "ai:photo:session:"
PHOTO_SESSION_URL_PREFIX = "ai:photo:session:url:"  # 持久化 URL
MAX_PHOTO_SIZE = 10 * 1024 * 1024  # 10MB 上限（base64 编码后约 13.3MB）

# 本地降级存储子目录名
_LOCAL_FALLBACK_SUBDIR = "user-photo"


def _get_local_fallback_dir() -> Path | None:
    """获取本地降级存储目录（与 model_service._save_to_local 对齐）

    路径 = settings.nginx_uploads_root / user-photo
    若 nginx_uploads_root 未配置，返回 None（降级不可用）
    """
    root = settings.nginx_uploads_root
    if not root:
        return None
    return Path(root) / _LOCAL_FALLBACK_SUBDIR


def _get_local_fallback_url_prefix() -> str:
    """获取本地降级存储的 URL 前缀"""
    return f"{settings.nginx_uploads_url_prefix.rstrip('/')}/{_LOCAL_FALLBACK_SUBDIR}"


def _save_to_local(image_data: bytes, user_id: int) -> str | None:
    """OSS 降级时把照片落地到 nginx 静态目录

    文件命名：{userId}_{uuid8}_{md5前8位}.jpg
    返回 nginx 访问 URL（如 /uploads/user-photo/1024_xxx.jpg）

    若 NGINX_UPLOADS_ROOT 未配置，返回 None（降级不可用）
    """
    local_dir = _get_local_fallback_dir()
    if local_dir is None:
        logger.warning("NGINX_UPLOADS_ROOT 未配置，用户照片无法本地降级存储: userId=%s", user_id)
        return None
    local_dir.mkdir(parents=True, exist_ok=True)
    md5_prefix = hashlib.md5(image_data).hexdigest()[:8]
    filename = f"{user_id}_{uuid.uuid4().hex[:8]}_{md5_prefix}.jpg"
    local_path = local_dir / filename
    local_path.write_bytes(image_data)
    url = f"{_get_local_fallback_url_prefix()}/{filename}"
    logger.info("用户照片 OSS 降级：已存本地: %s", url)
    return url


async def _upload_photo_to_storage(image_bytes: bytes, user_id: int, oss_uploader) -> str | None:
    """上传照片到 OSS（或本地降级），返回 URL

    Args:
        image_bytes: 照片二进制数据
        user_id: 用户 ID（日志用）
        oss_uploader: OssUploader 实例（可为 None，则直接本地降级）
    Returns:
        OSS URL 或本地 URL；都不可用时返回 None
    """
    # 1. 优先 OSS
    if oss_uploader is not None:
        try:
            date_str = datetime.now().strftime("%Y%m%d")
            directory = f"user-photo/{date_str}"
            url = await asyncio.to_thread(
                oss_uploader.upload_image,
                image_bytes,
                directory,
                "jpg",
            )
            if url:
                logger.info("用户照片已上传 OSS: userId=%s, url=%s", user_id, url)
                return url
        except Exception as e:
            logger.warning("用户照片 OSS 上传失败，尝试本地降级: userId=%s, error=%s", user_id, e)

    # 2. 本地降级
    return _save_to_local(image_bytes, user_id)


class PhotoSessionService:

    def __init__(self, redis: aioredis.Redis, oss_uploader=None):
        """
        Args:
            redis: Redis 连接
            oss_uploader: OssUploader 实例（可为 None，则仅本地降级）
        """
        self.redis = redis
        self.oss_uploader = oss_uploader

    async def upload_photo(self, user_id: int, photo_base64: str) -> str:
        """上传照片到 Redis 会话 + 持久化到 OSS/本地

        持久化策略：
          - 除 Redis base64 缓存外，同步把照片 bytes 上传到 OSS（或本地降级）
          - URL 存入 Redis ai:photo:session:url:{userId}:{sessionId}（与 base64 同 TTL）
          - accept 入库时通过 get_photo_url 读取 URL

        校验 base64 大小（≤10MB 原始图片，base64 编码后约 13.3MB）
        生成唯一 sessionId，Redis Key 含 sessionId 维度，多设备互不覆盖

        Returns:
            photoSessionKey（= "{userId}:{sessionId}"，多设备隔离）
        Raises:
            ValueError: 照片超过大小限制
        """
        # base64 大小校验（base64 编码后约为原始大小的 4/3）
        if len(photo_base64) > MAX_PHOTO_SIZE * 4 // 3:
            logger.warning("照片超过大小限制: userId=%s, size=%d bytes",
                           user_id, len(photo_base64))
            raise ValueError(f"照片超过大小限制（最大 {MAX_PHOTO_SIZE // 1024 // 1024}MB）")

        # 生成唯一 sessionId，多设备隔离
        session_id = uuid.uuid4().hex[:12]
        session_key = f"{user_id}:{session_id}"

        # 解码 base64 → 持久化到 OSS / 本地降级
        photo_url: str | None = None
        try:
            image_bytes = base64.b64decode(photo_base64)
            photo_url = await _upload_photo_to_storage(image_bytes, user_id, self.oss_uploader)
        except Exception as e:
            logger.warning("照片持久化失败（不阻塞主流程，accept 时为 None）: userId=%s, error=%s",
                           user_id, e)

        # Redis 存 base64（VTON 输入用，key 含 sessionId 维度）
        key = f"{PHOTO_SESSION_PREFIX}{session_key}"
        await self.redis.set(key, photo_base64, ex=PHOTO_SESSION_TTL)

        # Redis 存 photo_url（accept 入库用）
        if photo_url:
            url_key = f"{PHOTO_SESSION_URL_PREFIX}{session_key}"
            await self.redis.set(url_key, photo_url, ex=PHOTO_SESSION_TTL)

        logger.info("照片已上传会话: userId=%s, sessionKey=%s, size=%d bytes, photoUrl=%s",
                    user_id, session_key, len(photo_base64), photo_url)
        return session_key

    async def clear_photo(self, user_id: int):
        """清除该用户所有设备的会话照片（base64 + URL）

        多设备隔离后，一个用户可能有多个 session，用 SCAN 清除全部。
        保留 user_id 参数（DELETE /photo 接口无 session_key），向后兼容。
        """
        # SCAN 删除 ai:photo:session:{userId}* 和 ai:photo:session:url:{userId}*
        base_pattern = f"{PHOTO_SESSION_PREFIX}{user_id}*"
        url_pattern = f"{PHOTO_SESSION_URL_PREFIX}{user_id}*"
        deleted = 0
        async for pattern in (base_pattern, url_pattern):
            async for key in self.redis.scan_iter(match=pattern, count=100):
                await self.redis.delete(key)
                deleted += 1
        logger.info("照片会话已清除: userId=%s, deletedKeys=%d", user_id, deleted)
