"""
时尚潮流搜索服务（基于 AnySearch API，替代旧 trend_service 的平台销量数据源）

用途：查询用户所在地区的实时时尚潮流信息，让 LLM 在搭配决策时参考真实社媒/通用资讯
接入环节：
    1. 节点3 outfit_combination → LLM select_top_outfits 前自动注入 extra_hints
    2. 决策子 Agent 通过 ReAct 工具 search_fashion_trend 自主深度查询

数据流：
    1. 根据用户 city/country 推断国家代码（CN/JP/KR/US/FR/GB/...）
    2. 取该地区的搜索策略（关键词模板 + 语言 + zone）
    3. 并行调 AnySearch 两个 tag：
       - social_media.social_media：搜社媒穿搭内容（Ins/小红书/Pinterest 等）
       - general.general：搜通用时尚文章（Vogue/Elle/时尚博客等）
    4. 合并去重 + 格式化为 LLM hint

设计原则：
1. 失败时降级返回空潮流，LLM 仅凭用户意图推理（不影响主流程）
2. 不同国家用不同搜索关键词（中国搜"小红书穿搭"、日本搜"原宿風"、美国搜"street style"）
3. AnySearch 是海外服务，走 settings.proxy_url 代理（与 Jina 一致）
4. Redis 缓存 600s（潮流更新不频繁，按 city+scene+style 缓存）
5. API Key 鉴权：Authorization: Bearer <KEY>
"""
import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# P0 缓存：潮流数据 Redis 缓存（按 city+scene+style_tags 缓存，TTL 600s）
_FASHION_TREND_CACHE_TTL = 600
_FASHION_TREND_CACHE_PREFIX = "ai:fashion_trend:"


# ============================================================
# 地区→潮流搜索策略映射（核心：不同国家搜不同平台和关键词）
# ============================================================
# 每个地区包含：
#   - social_kw: 社媒搜索关键词模板（拼在用户 query 后面）
#   - general_kw: 通用搜索关键词模板
#   - language: 偏好语言（传给 AnySearch）
#   - zone: 搜索区域 cn/intl
#   - region_label: 地区中文标签（用于 hint 展示）
REGIONAL_FASHION_STRATEGY: dict[str, dict[str, Any]] = {
    "CN": {
        "social_kw": "小红书穿搭 网红同款",
        "general_kw": "中国时尚趋势 当季流行穿搭",
        "language": "zh-CN",
        "zone": "cn",
        "region_label": "中国",
    },
    "JP": {
        "social_kw": "原宿風 ストリートファッション 日本人コーデ",
        "general_kw": "日本 时尚趋势 和風穿搭",
        "language": "ja",
        "zone": "intl",
        "region_label": "日本",
    },
    "KR": {
        "social_kw": "K패션 한국 스타일 스트릿 패션",
        "general_kw": "韩国时尚 K-fashion trend",
        "language": "ko",
        "zone": "intl",
        "region_label": "韩国",
    },
    "US": {
        "social_kw": "street style fashion influencer outfit ideas",
        "general_kw": "fashion trend US style guide",
        "language": "en",
        "zone": "intl",
        "region_label": "美国",
    },
    "GB": {
        "social_kw": "street style london british fashion outfit inspiration",
        "general_kw": "fashion trend UK style guide",
        "language": "en",
        "zone": "intl",
        "region_label": "英国",
    },
    "FR": {
        "social_kw": "look mode style parisien fashion blog",
        "general_kw": "tendance mode fashion week paris",
        "language": "fr",
        "zone": "intl",
        "region_label": "法国",
    },
    "IT": {
        "social_kw": "look moda stile italiano fashion blog",
        "general_kw": "tendenza moda italian fashion",
        "language": "it",
        "zone": "intl",
        "region_label": "意大利",
    },
    "DE": {
        "social_kw": "outfit ideen mode blog street style",
        "general_kw": "modetrend german fashion",
        "language": "de",
        "zone": "intl",
        "region_label": "德国",
    },
    "AU": {
        "social_kw": "aussie street style outfit inspiration fashion blogger",
        "general_kw": "fashion trend australia style",
        "language": "en",
        "zone": "intl",
        "region_label": "澳大利亚",
    },
    "CA": {
        "social_kw": "canadian street style outfit ideas fashion blog",
        "general_kw": "fashion trend canada style guide",
        "language": "en",
        "zone": "intl",
        "region_label": "加拿大",
    },
}

# 默认策略（未识别的国家）：走 intl + en
_DEFAULT_STRATEGY: dict[str, Any] = {
    "social_kw": "street style outfit inspiration fashion trend",
    "general_kw": "fashion trend style guide",
    "language": "en",
    "zone": "intl",
    "region_label": "全球",
}

# 城市→国家代码映射（用于从 city 推断 country，IP 定位拿到的是城市名）
# 中文城市名→CN，日韩欧美主要城市显式映射，其他默认走 intl
_CITY_TO_COUNTRY: dict[str, str] = {
    # 中国主要城市（中文）
    "北京": "CN", "上海": "CN", "广州": "CN", "深圳": "CN", "杭州": "CN",
    "成都": "CN", "重庆": "CN", "武汉": "CN", "西安": "CN", "南京": "CN",
    "天津": "CN", "苏州": "CN", "厦门": "CN", "长沙": "CN", "青岛": "CN",
    "哈尔滨": "CN", "沈阳": "CN", "大连": "CN", "济南": "CN", "郑州": "CN",
    # 日本
    "Tokyo": "JP", "Osaka": "JP", "Kyoto": "JP", "东京": "JP", "大阪": "JP", "京都": "JP",
    # 韩国
    "Seoul": "KR", "Busan": "KR", "首尔": "KR", "釜山": "KR",
    # 美国
    "New York": "US", "Los Angeles": "US", "Chicago": "US", "San Francisco": "US",
    "Seattle": "US", "Boston": "US", "Miami": "US", "纽约": "US", "洛杉矶": "US",
    # 英国
    "London": "GB", "Manchester": "GB", "伦敦": "GB",
    # 法国
    "Paris": "FR", "Marseille": "FR", "巴黎": "FR",
    # 意大利
    "Rome": "IT", "Milan": "IT", "米兰": "IT", "罗马": "IT",
    # 德国
    "Berlin": "DE", "Munich": "DE", "柏林": "DE", "慕尼黑": "DE",
    # 澳大利亚
    "Sydney": "AU", "Melbourne": "AU", "悉尼": "AU", "墨尔本": "AU",
    # 加拿大
    "Toronto": "CA", "Vancouver": "CA", "多伦多": "CA", "温哥华": "CA",
}


def infer_country(city: str = "", country: str = "") -> str:
    """从 city/country 推断国家代码

    优先级：
    1. 显式传入的 country（ISO 国家代码如 CN/JP/US）
    2. 城市名→国家映射表
    3. 中文字符判断→CN
    4. 默认走 INTL（全球通用策略）
    """
    # 1. 显式 country
    if country and country.upper() in REGIONAL_FASHION_STRATEGY:
        return country.upper()
    # 2. 城市名映射
    if city:
        city_stripped = city.strip()
        if city_stripped in _CITY_TO_COUNTRY:
            return _CITY_TO_COUNTRY[city_stripped]
        # 3. 中文字符 → CN
        if any('\u4e00' <= c <= '\u9fff' for c in city_stripped):
            return "CN"
    # 4. 默认
    return "INTL"


def _build_query(base: str, region_kw: str) -> str:
    """拼接用户 query 和地区关键词

    Args:
        base: 用户原始 query（场景+风格标签拼接，如 "通勤 简约"）
        region_kw: 地区关键词模板（如 "小红书穿搭 网红同款"）
    """
    base = (base or "").strip()
    region_kw = (region_kw or "").strip()
    if base and region_kw:
        return f"{base} {region_kw}"
    return base or region_kw


async def _call_anysearch(
    api_url: str,
    api_key: str,
    query: str,
    tag: str,
    language: str,
    zone: str,
    max_results: int = 5,
    proxy_url: str = "",
) -> list[dict]:
    """调用 AnySearch API 单次搜索

    Args:
        api_url: AnySearch API 地址
        api_key: API Key
        query: 搜索关键词
        tag: 数据源标签（social_media.social_media / general.general）
        language: 偏好语言
        zone: 区域 cn/intl
        max_results: 返回数量
        proxy_url: 代理地址（海外服务需要）

    Returns:
        结果列表 [{title, url, snippet, content}, ...]
    """
    if not api_key:
        logger.warning("[时尚潮流] AnySearch API Key 未配置，跳过搜索")
        return []
    if not query:
        return []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "tag": tag,
        "max_results": max_results,
        "language": language,
        "zone": zone,
        "format": "json",
    }

    try:
        # AnySearch 是海外服务，走代理（与 Jina 一致）
        proxies = proxy_url if proxy_url else None
        async with httpx.AsyncClient(trust_env=False, timeout=10.0, proxy=proxies) as client:
            resp = await client.post(api_url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    "[时尚潮流] AnySearch 调用失败: status=%s, tag=%s, query=%s",
                    resp.status_code, tag, query,
                )
                return []
            data = resp.json()
            # AnySearch 返回结构：{"code": 0, "data": {"results": [...]}}
            if isinstance(data, dict):
                results = (
                    data.get("data", {}).get("results")
                    or data.get("results")
                    or []
                )
                if isinstance(results, list):
                    return results
            return []
    except Exception as e:
        logger.warning("[时尚潮流] AnySearch 调用异常: tag=%s, error=%s", tag, e)
        return []


def _merge_results(
    social_results: list[dict],
    general_results: list[dict],
) -> list[dict]:
    """合并去重两个 tag 的搜索结果

    Returns:
        合并后的结果列表，每项附加 source 字段（social/general）
    """
    seen_urls: set[str] = set()
    merged: list[dict] = []

    for r in social_results:
        url = r.get("url", "")
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        merged.append({**r, "source": "social_media"})

    for r in general_results:
        url = r.get("url", "")
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        merged.append({**r, "source": "general"})

    return merged


async def get_fashion_trends(
    city: str = "",
    country: str = "",
    scene: str = "",
    style_tags: list[str] | None = None,
    api_key: str = "",
    api_url: str = "https://api.anysearch.com/v1/search",
    proxy_url: str = "",
    redis=None,
) -> dict:
    """查询地区时尚潮流信息（AnySearch API）

    并行调 social_media.social_media + general.general 两个 tag，
    根据国家/地区路由不同的搜索关键词。

    Args:
        city: 城市名（中文或英文，如 "北京"/"Tokyo"）
        country: 国家代码（如 "CN"/"JP"），空时从 city 推断
        scene: 用户场景描述（如 "通勤"/"约会"）
        style_tags: 用户选的风格标签列表（如 ["简约", "休闲"]）
        api_key: AnySearch API Key
        api_url: AnySearch API 地址
        proxy_url: 代理地址（海外服务需要）
        redis: 可选 Redis 客户端，启用缓存

    Returns:
        {
            "city": "北京",
            "country": "CN",
            "region_label": "中国",
            "query_base": "通勤 简约",
            "social_results": [...],
            "general_results": [...],
            "merged_results": [...],
            "total": 8,
            "data_source": "anysearch_api",
        }
    """
    # 1. 推断国家
    country_code = infer_country(city, country)
    strategy = REGIONAL_FASHION_STRATEGY.get(country_code, _DEFAULT_STRATEGY)

    # 2. 构造基础 query（场景 + 风格标签）
    base_parts = []
    if scene:
        base_parts.append(scene)
    if style_tags:
        base_parts.extend(style_tags)
    query_base = " ".join(base_parts).strip()

    # 3. 查 Redis 缓存（命中直接返回）
    cache_key = (
        f"{_FASHION_TREND_CACHE_PREFIX}"
        f"{country_code}:{query_base or 'all'}"
    )
    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached is not None:
                try:
                    return json.loads(cached)
                except (TypeError, ValueError) as e:
                    logger.warning("[时尚潮流] Redis 缓存反序列化失败，回源: %s", e)
        except Exception as e:
            logger.warning("[时尚潮流] Redis 缓存读取失败（降级直查）: %s", e)

    # 4. 构造两个 tag 的查询
    social_query = _build_query(query_base, strategy["social_kw"])
    general_query = _build_query(query_base, strategy["general_kw"])

    # 5. 并行调两个 tag
    social_task = _call_anysearch(
        api_url, api_key, social_query, "social_media.social_media",
        strategy["language"], strategy["zone"], max_results=5, proxy_url=proxy_url,
    )
    general_task = _call_anysearch(
        api_url, api_key, general_query, "general.general",
        strategy["language"], strategy["zone"], max_results=5, proxy_url=proxy_url,
    )
    social_results, general_results = await asyncio.gather(
        social_task, general_task, return_exceptions=True,
    )

    # 容错：gather 返回异常时降级为空列表
    if isinstance(social_results, Exception):
        logger.warning("[时尚潮流] social_media 搜索异常: %s", social_results)
        social_results = []
    if isinstance(general_results, Exception):
        logger.warning("[时尚潮流] general 搜索异常: %s", general_results)
        general_results = []

    # 6. 合并去重
    merged = _merge_results(social_results, general_results)

    result = {
        "city": city,
        "country": country_code,
        "region_label": strategy["region_label"],
        "query_base": query_base,
        "social_query": social_query,
        "general_query": general_query,
        "social_results": social_results,
        "general_results": general_results,
        "merged_results": merged,
        "total": len(merged),
        "data_source": "anysearch_api",
    }

    # 7. 写 Redis 缓存
    if redis is not None and merged:
        try:
            await redis.set(
                cache_key,
                json.dumps(result, ensure_ascii=False),
                ex=_FASHION_TREND_CACHE_TTL,
            )
        except Exception as e:
            logger.warning("[时尚潮流] Redis 缓存写入失败: %s", e)

    logger.info(
        "[时尚潮流] 地区=%s(%s), query_base=%s, social=%d 条, general=%d 条, 合并=%d 条",
        country_code, strategy["region_label"], query_base or "无",
        len(social_results), len(general_results), len(merged),
    )
    return result


def format_fashion_trend_hint_for_llm(trend_data: dict) -> str:
    """把时尚潮流搜索结果格式化为 LLM 可读的提示文本

    设计原则：
    1. 明确告知 LLM 这是该地区当季的社媒/资讯潮流参考
    2. 区分社媒内容（网红同款/街拍）和通用文章（时尚趋势分析）
    3. LLM 应参考但不必照搬，优先满足用户个人需求
    4. 不同国家潮流差异大，LLM 应尊重地区差异
    """
    if not trend_data:
        return ""
    if not isinstance(trend_data, dict):
        return ""

    merged = trend_data.get("merged_results") or []
    if not merged:
        return ""

    region_label = trend_data.get("region_label", "全球")
    country = trend_data.get("country", "")
    query_base = trend_data.get("query_base", "")

    # 分组展示
    social_items = [r for r in merged if r.get("source") == "social_media"]
    general_items = [r for r in merged if r.get("source") == "general"]

    def _format_item(item: dict, idx: int) -> str:
        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or item.get("content") or "").strip()
        url = item.get("url", "")
        # snippet 过长截断（避免 LLM 上下文爆炸）
        if len(snippet) > 200:
            snippet = snippet[:200] + "..."
        parts = [f"  {idx}. {title}"]
        if snippet:
            parts.append(f"     摘要: {snippet}")
        if url:
            parts.append(f"     来源: {url}")
        return "\n".join(parts)

    blocks = []
    if social_items:
        social_block = "【社媒潮流（网红同款/街拍/用户实拍）】\n" + "\n".join(
            _format_item(r, i + 1) for i, r in enumerate(social_items[:5])
        )
        blocks.append(social_block)

    if general_items:
        general_block = "【时尚资讯（趋势分析/杂志文章/搭配指南）】\n" + "\n".join(
            _format_item(r, i + 1) for i, r in enumerate(general_items[:5])
        )
        blocks.append(general_block)

    if not blocks:
        return ""

    query_hint = f"（基于用户场景/风格：{query_base}）" if query_base else ""

    return (
        f"【{region_label}地区当季时尚潮流参考】{query_hint}\n"
        f"数据源：AnySearch 实时搜索（社媒+通用）\n\n"
        + "\n\n".join(blocks)
        + "\n\n【潮流参考原则】\n"
        f"1. 以上是 {region_label} 地区当季的社媒穿搭和时尚资讯，供搭配灵感参考\n"
        "2. 不同国家/地区潮流差异大（如日本原宿风、法国极简优雅、韩国K-fashion），"
        "应尊重地区审美差异\n"
        "3. 优先满足用户的个人风格和场景需求，潮流仅作辅助参考，不必照搬\n"
        "4. 社媒内容偏实时街拍/网红同款，通用文章偏趋势分析，可综合参考\n"
        "5. 若搜索结果与用户需求冲突，以用户需求为准"
    )
