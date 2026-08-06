"""
阿里云 OSS 连接管理
"""
import logging
import oss2

logger = logging.getLogger(__name__)


class OssClientWrapper:
    """OSS 客户端封装"""

    def __init__(
        self,
        endpoint: str = "",
        access_key_id: str = "",
        access_key_secret: str = "",
        bucket_name: str = "zmall-ai",
    ):
        self.endpoint = endpoint
        self.access_key_id = access_key_id
        self.access_key_secret = access_key_secret
        self.bucket_name = bucket_name
        self._bucket: oss2.Bucket | None = None

    def get_bucket(self) -> oss2.Bucket | None:
        """获取 OSS Bucket 实例（配置为空时返回 None，降级为本地存储）"""
        if not self.endpoint or not self.access_key_id:
            logger.warning("OSS 配置不完整，降级为本地存储")
            return None
        if self._bucket is None:
            auth = oss2.Auth(self.access_key_id, self.access_key_secret)
            self._bucket = oss2.Bucket(auth, self.endpoint, self.bucket_name)
            logger.info("OSS 客户端已连接: bucket=%s", self.bucket_name)
        return self._bucket
