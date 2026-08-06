"""
Qdrant 向量数据库连接管理

支持两种部署：
- 本地 Docker: host=192.168.59.128, port=6333, http
- Qdrant Cloud: host=xxx.qdrant.io, port=6333, https, 需要 api_key

通过 .env 的 QDRANT_HOST / QDRANT_API_KEY / QDRANT_PREFIX 配置。

代理兼容性说明：
    qdrant-client 1.8.0 与 httpx 0.28+ 不兼容 —— QdrantClient(http_client=...)
    参数会被 qdrant-client 内部错误透传给 httpx.Client()，httpx 0.28 不接受此参数。
    本封装改用环境变量 HTTPS_PROXY/HTTP_PROXY 配置代理，httpx 自动读取，兼容所有版本。
"""
import logging
import os

from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

# Collection 常量
COLLECTION_ITEM_STYLE = "item_style"

# 本地/内网地址不走代理（避免本地 Qdrant 也走代理）
# 同时排除阿里百炼 LLM/千问 API，避免代理 SSL 握手失败
# 注：阿里百炼在杭州，是国内服务，不应走海外代理
_NO_PROXY_ADDRS = ("localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8,172.16.0.0/12,"
                   "dashscope.aliyuncs.com,aliyuncs.com")


class QdrantClientWrapper:
    """Qdrant 客户端封装（单例，支持本地和云服务）"""

    _instance: QdrantClient | None = None

    def __init__(
        self,
        host: str = "192.168.59.128",
        port: int = 6333,
        api_key: str = "",
        prefix: str = "",
        use_ssl: bool = False,
        proxy_url: str = "",
    ):
        self.host = host
        self.port = port
        self.api_key = api_key or None
        self.prefix = prefix or None
        # 云服务 URL 以 https 开头时自动启用 SSL
        self.use_ssl = use_ssl or host.startswith("https://") or port == 443
        self.proxy_url = proxy_url

    def get_client(self) -> QdrantClient:
        if self._instance is None:
            # 去掉协议前缀，qdrant-client 的 host 参数只接受裸主机名
            host = self.host.replace("https://", "").replace("http://", "")

            # Qdrant Cloud 在海外，需要代理才能稳定访问
            # qdrant-client 1.8.0 与 httpx 0.28+ 不兼容（http_client 参数透传 bug），
            # 改用环境变量配置代理，httpx 会自动读取。
            # 副作用：进程内所有 httpx 请求都会走代理，但本地/内网地址通过 NO_PROXY 排除。
            if self.proxy_url:
                os.environ["HTTP_PROXY"] = self.proxy_url
                os.environ["HTTPS_PROXY"] = self.proxy_url
                os.environ["NO_PROXY"] = _NO_PROXY_ADDRS
                logger.info("Qdrant 客户端启用代理（环境变量）: %s", self.proxy_url)

            client_kwargs = {
                "host": host,
                "port": self.port,
                "api_key": self.api_key,
                "prefix": self.prefix,
                "https": self.use_ssl,
            }
            self._instance = QdrantClient(**client_kwargs)
            logger.info(
                "Qdrant 客户端已连接: %s://%s:%s (api_key=%s, cloud=%s)",
                "https" if self.use_ssl else "http",
                host, self.port,
                "已配置" if self.api_key else "无",
                self.use_ssl,
            )
        return self._instance

    def ensure_collections(self, max_retries: int = 3, retry_delay: float = 3.0):
        """启动时确保所需 Collection 存在

        通过代理访问 Qdrant Cloud 时，TLS 握手可能偶发失败，
        加重试机制应对代理不稳定。

        Args:
            max_retries: 最大重试次数（默认 3 次）
            retry_delay: 重试间隔秒数
        """
        import time
        from qdrant_client.http.models import Distance, VectorParams

        client = self.get_client()
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                collections = {c.name for c in client.get_collections().collections}
                break
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    logger.warning(
                        "Qdrant get_collections 失败（第 %d/%d 次重试），%ss 后重试: %s",
                        attempt + 1, max_retries, retry_delay, e,
                    )
                    time.sleep(retry_delay)
                else:
                    logger.error("Qdrant get_collections 重试 %d 次后仍失败: %s", max_retries, e)
                    raise
        else:
            raise last_error  # 理论上不会走到这里

        if COLLECTION_ITEM_STYLE not in collections:
            client.create_collection(
                collection_name=COLLECTION_ITEM_STYLE,
                # jina-clip-v2 原生 1024 维（与 EmbedClient.vector_dim 默认值对齐）
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )
            logger.info("Qdrant Collection 已创建: %s", COLLECTION_ITEM_STYLE)

        # 为过滤字段创建 payload 索引（Qdrant Cloud 要求过滤字段必须建索引）
        # create_payload_index 是幂等操作，已存在则跳过
        _ensure_item_style_indices(client)


def _ensure_item_style_indices(client):
    """为 item_style collection 的过滤字段创建 payload 索引（幂等）

    Qdrant Cloud 及近版本 Qdrant 要求 filter/must 条件涉及的字段必须有对应类型的索引，
    否则搜索返回 400: "Index required but not found for ...".

    字段类型依据 indexer.py 写入的 payload 类型：
    - is_active: bool（MatchValue 过滤）
    - stock: integer（Range 过滤，必须 integer 类型索引）
    - shop_id: integer（MatchAny 过滤）
    - category / color / season / target_gender: keyword（MatchValue/MatchAny 过滤）
    """
    index_specs = [
        ("is_active", "bool"),
        ("stock", "integer"),
        ("shop_id", "integer"),
        ("category", "keyword"),
        ("color", "keyword"),
        ("season", "keyword"),
        ("target_gender", "keyword"),
    ]
    for field_name, field_schema in index_specs:
        try:
            client.create_payload_index(
                collection_name=COLLECTION_ITEM_STYLE,
                field_name=field_name,
                field_schema=field_schema,
            )
        except Exception as e:
            # 已存在索引时 Qdrant 会抛异常，静默跳过
            if "already" not in str(e).lower():
                logger.debug("创建索引 %s.%s 跳过: %s", COLLECTION_ITEM_STYLE, field_name, e)
