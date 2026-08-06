"""AI 随心搭共享模块（商品驱动模式 ai-models + 风格驱动模式 ai-outfit 共用）

抽自原 ai-models/app/services/outfit_service.py 和 ai-outfit/app/tools/nodes.py
的重复实现，避免"改一处必须同步改另一处"的技术债。

包含四部分：
- image_compose: PIL 多件换装合成 + 辅助品类区域映射
- session_counter: "换一套"会话计数 Lua + 计数/扣费判断
- category_validator: 品类组合校验（全身套装与上衣/下装互斥 + 动态超时估算）
- url_safety: SSRF 防护（图片下载前校验 URL 不指向内网）
"""
import ipaddress
from urllib.parse import urlparse

from shared.outfit_common.image_compose import (
    AUX_CATEGORY_REGION,
    compose_full_outfit_image,
)
from shared.outfit_common.session_counter import (
    SESSION_COUNT_PREFIX,
    SESSION_COUNT_TTL,
    session_key,
    should_deduct,
    incr_and_get_old_count,
    decr_session_count,
)
from shared.outfit_common.category_validator import (
    ALL_OUTFIT_CATEGORIES,
    VTON_CATEGORIES,
    WAN_ACCESSORY_CATEGORIES,
    MAX_ITEMS_PER_OUTFIT,
    CategoryConflictError,
    validate_category_combination,
    filter_conflicting_categories,
    estimate_vton_timeout,
    count_vton_categories,
)


def is_safe_image_url(url: str) -> bool:
    """SSRF 防护：校验图片 URL 是否安全

    拦截场景：
    - 非 http/https 协议（file://, gopher://, dict:// 等）
    - 链路本地 169.254.0.0/16（含 AWS 元数据 169.254.169.254）
    - 唯一本地地址 fc00::/7

    放行场景（业务需求）：
    - localhost / 127.0.0.1（同机 nginx 静态资源）
    - 私有网段 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16（内网 nginx / Java 服务）
    原因：模特图、商品图 URL 来自 Java item-service（可信源），
    指向内网 nginx 静态资源，属于正常业务调用，非用户直接输入。
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    hostname = parsed.hostname
    if not hostname:
        return False
    try:
        ip = ipaddress.ip_address(hostname)
        # 仅拦截链路本地和保留地址（元数据地址风险）
        if ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        pass  # 非 IP 格式（域名/localhost），放行
    return True


__all__ = [
  # image_compose
  "AUX_CATEGORY_REGION",
  "compose_full_outfit_image",
  # session_counter
  "SESSION_COUNT_PREFIX",
  "SESSION_COUNT_TTL",
  "session_key",
  "should_deduct",
  "incr_and_get_old_count",
  "decr_session_count",
  # category_validator
  "ALL_OUTFIT_CATEGORIES",
  "VTON_CATEGORIES",
  "WAN_ACCESSORY_CATEGORIES",
  "MAX_ITEMS_PER_OUTFIT",
  "CategoryConflictError",
  "validate_category_combination",
  "filter_conflicting_categories",
  "estimate_vton_timeout",
  "count_vton_categories",
  # url_safety
  "is_safe_image_url",
]
