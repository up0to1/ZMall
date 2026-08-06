"""
OSS 上传 / 本地降级存储

OSS 配置完整时上传到阿里云 OSS；配置缺失时降级为本地文件存储，
写入 nginx 静态资源目录（如 zmall-nginx/html/uploads/），
返回相对 URL（如 /uploads/outfit-results/20260802/xxx.jpg）供前端访问。
"""
import logging
import os
import uuid
from datetime import datetime

from shared.oss_client.client import OssClientWrapper

logger = logging.getLogger(__name__)


class OssUploader:
    """OSS 文件上传器（配置缺失时自动降级为本地文件存储）"""

    def __init__(
        self,
        client_wrapper: OssClientWrapper,
        url_prefix: str = "",
        local_root: str = "",
        local_url_prefix: str = "/uploads",
    ):
        """
        Args:
            client_wrapper: OSS 客户端封装
            url_prefix: OSS URL 前缀（留空自动拼接）
            local_root: 本地存储根目录（nginx 静态资源目录，如 .../html/uploads）
            local_url_prefix: 本地存储返回的 URL 前缀（如 /uploads）
        """
        self.client_wrapper = client_wrapper
        self.url_prefix = url_prefix or f"https://{client_wrapper.bucket_name}.{client_wrapper.endpoint.replace('https://', '')}"
        self.local_root = local_root.rstrip("/") if local_root else ""
        self.local_url_prefix = local_url_prefix.rstrip("/") if local_url_prefix else "/uploads"

    def upload_image(
        self,
        file_data: bytes,
        directory: str = "outfit",
        file_ext: str = "jpg",
    ) -> str | None:
        """上传图片，返回 URL

        OSS 配置完整时上传到 OSS；否则降级为本地文件存储。
        两者都不可用时返回 None。

        Args:
            file_data: 图片二进制数据
            directory: 子目录（outfit / outfit-results / model-images 等）
            file_ext: 文件扩展名
        Returns:
            OSS URL 或本地相对 URL，均不可用时返回 None
        """
        # 优先走 OSS
        bucket = self.client_wrapper.get_bucket()
        if bucket is not None:
            date_str = datetime.now().strftime("%Y%m%d")
            filename = f"{directory}/{date_str}/{uuid.uuid4().hex}.{file_ext}"
            bucket.put_object(filename, file_data)
            url = f"{self.url_prefix}/{filename}"
            logger.info("图片已上传 OSS: %s", url)
            return url

        # OSS 未配置 → 本地文件存储
        if not self.local_root:
            logger.warning("OSS 未配置且 local_root 为空，无法存储图片")
            return None

        date_str = datetime.now().strftime("%Y%m%d")
        filename = f"{uuid.uuid4().hex}.{file_ext}"
        dir_path = os.path.join(self.local_root, directory, date_str)
        os.makedirs(dir_path, exist_ok=True)
        file_path = os.path.join(dir_path, filename)
        try:
            with open(file_path, "wb") as f:
                f.write(file_data)
            url = f"{self.local_url_prefix}/{directory}/{date_str}/{filename}"
            logger.info("图片已存储到本地: %s", url)
            return url
        except Exception as e:
            logger.error("本地图片存储失败: dir=%s, error=%s", directory, e)
            return None
