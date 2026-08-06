"""
流行趋势服务（基于平台销量数据 + Qdrant 向量聚类）

用途：查询某品类的流行风格，让 LLM 在搭配决策时参考当下热销商品
接入环节：节点3 outfit_combination → LLM select_top_outfits 前作为参考上下文

数据流：
    1. 调 Java item-service GET /items/internal/trending 获取近 N 天销量 TopK 商品
    2. 用 Jina CLIP 编码商品图片向量
    3. 简单 K-means 聚类（基于余弦相似度）找出 Top3 风格簇
    4. 每簇取代表商品 + 描述风格特征

设计原则：
1. 失败时降级返回空趋势，LLM 仅凭用户意图推理（不影响主流程）
2. Jina 编码走代理（海外服务），与现有 embed_client 共享配置
3. 聚类用最简单的向量平均（避免引入 scikit-learn 依赖）
"""
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


# 趋势数据 Redis 缓存（趋势更新不频繁，TTL 600s）
_TREND_CACHE_TTL = 600
_TREND_CACHE_PREFIX = "ai:trend:"


def _to_jsonable(obj):
    """JSON 序列化兜底：numpy 类型转 Python 原生类型"""
    try:
        import numpy as np
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
    except ImportError:
        pass
    return str(obj)


async def get_trending_styles(
    java_client,
    embed_client,
    category: str = "",
    top_k: int = 50,
    cluster_k: int = 3,
    days: int = 30,
    redis=None,  # 可选 Redis 客户端，启用缓存；None 时降级直查
) -> dict:
    """获取某品类的流行风格

    Args:
        java_client: JavaClient 实例（用于调用 item-service）
        embed_client: EmbedClient 实例（用于 Jina 向量编码）
        category: 商品类目（中文，如 "上衣"），空字符串查全品类
        top_k: 返回前 K 条热销商品
        cluster_k: 风格聚类数（默认 3）
        days: 销量回溯天数
        redis: 可选 Redis 客户端（aioredis），启用缓存；None 时降级直查

    Returns:
        {
            "trending_styles": [
                {
                    "style_name": "简约通勤风",
                    "score": 0.85,
                    "representative_items": [{"id": 101, "name": "...", "image": "..."}],
                    "key_features": ["纯色", "修身", "基础款"],
                    "item_count": 18,
                },
                ...
            ],
            "total_items": 50,
            "category": "上衣",
            "data_source": "platform_sales",
            "lookback_days": 30,
        }
    """
    fallback = {"trending_styles": [], "category": category, "error": None}

    # 查 Redis 缓存（命中直接返回，未命中回源）
    if redis is not None:
        cache_key = f"{_TREND_CACHE_PREFIX}{category if category else 'all'}:{days}:{top_k}"
        try:
            cached = await redis.get(cache_key)
            if cached is not None:
                try:
                    return json.loads(cached)
                except (TypeError, ValueError) as e:
                    logger.warning("[趋势工具] Redis 缓存反序列化失败，回源: %s", e)
        except Exception as e:
            logger.warning("[趋势工具] Redis 缓存读取失败（降级直查）: %s", e)

    # 1. 查询热销商品
    try:
        resp = await java_client._call(
            "item-service", "GET", "/items/internal/trending",
            params={"category": category or "", "days": days, "topK": top_k},
        )
        if resp is None or resp.status_code != 200:
            logger.warning("[趋势工具] 查询热销商品失败: status=%s",
                           resp.status_code if resp else "None")
            return {**fallback, "error": "item-service 不可用"}
        trending_items = resp.json()
        # 兼容包装格式
        if isinstance(trending_items, dict) and "data" in trending_items:
            trending_items = trending_items["data"]
        if not isinstance(trending_items, list) or not trending_items:
            return {**fallback, "error": "无热销商品数据"}
    except Exception as e:
        logger.warning("[趋势工具] 查询热销商品异常: %s", e)
        return {**fallback, "error": str(e)}

    # 2. 编码商品文本向量（纯文本向量模式，并行 + 失败容忍）
    # 拼接商品文本（name + category + color + styleTags）后编码
    item_text_pairs = [(it, _build_trend_item_text(it)) for it in trending_items]
    if not item_text_pairs:
        return {**fallback, "error": "热销商品无有效文本"}

    texts = [text for _, text in item_text_pairs]
    vectors = await _batch_encode_texts(embed_client, texts)
    # 用 pairs 与 vectors 配对，避免错位
    valid_pairs = [(item, vec) for (item, _), vec in zip(item_text_pairs, vectors) if vec]
    if len(valid_pairs) < cluster_k:
        logger.warning("[趋势工具] 有效向量不足 %d，跳过聚类", cluster_k)
        return {**fallback, "error": "向量编码失败"}

    # 3. K-means 聚类（基于余弦相似度，放线程池避免阻塞事件循环）
    clusters = await asyncio.to_thread(
        _kmeans_cosine,
        vectors=[vec for _, vec in valid_pairs],
        items=[item for item, _ in valid_pairs],
        k=cluster_k,
    )

    # 4. 构造每个簇的趋势风格描述
    trending_styles = []
    for cluster_idx, cluster_items in enumerate(clusters):
        if not cluster_items:
            continue
        # 取该簇中销量最高的作为代表
        cluster_items_sorted = sorted(
            cluster_items,
            key=lambda x: x.get("sold", 0) or 0,
            reverse=True,
        )
        representatives = cluster_items_sorted[:3]
        # 简单特征提取：颜色/类目分布
        key_features = _extract_style_features(cluster_items)
        style_name = _generate_style_name(cluster_idx, key_features)
        # 该簇销量占总销量的比例作为 score
        total_sold = sum(it.get("sold", 0) or 0 for it in cluster_items)
        all_sold = sum(it.get("sold", 0) or 0 for _, it in valid_pairs)
        score = (total_sold / all_sold) if all_sold > 0 else 0.0

        trending_styles.append({
            "style_name": style_name,
            "score": round(score, 3),
            "representative_items": [
                {"id": it.get("id"), "name": it.get("name"),
                 "image": it.get("image"), "price": it.get("price"),
                 "sold": it.get("sold")}
                for it in representatives
            ],
            "key_features": key_features,
            "item_count": len(cluster_items),
        })

    # 按 score 降序
    trending_styles.sort(key=lambda x: x["score"], reverse=True)

    result = {
        "trending_styles": trending_styles,
        "total_items": len(valid_pairs),
        "category": category or "全品类",
        "data_source": "platform_sales",
        "lookback_days": days,
        "error": None,
    }

    # 回填 Redis 缓存（仅缓存成功结果，不缓存 fallback 错误结果）
    if redis is not None:
        try:
            await redis.set(
                cache_key,
                json.dumps(result, default=_to_jsonable),
                ex=_TREND_CACHE_TTL,
            )
        except Exception as e:
            logger.warning("[趋势工具] Redis 缓存回填失败（不影响主流程）: %s", e)

    return result


def _build_trend_item_text(item: dict) -> str:
    """从趋势商品拼接文本用于向量编码（纯文本向量模式）

    拼接 name + category + color + styleTags，与 index_items.py 逻辑一致。
    """
    parts = []
    name = item.get("name")
    if name:
        parts.append(str(name).strip())
    category = item.get("category")
    if category:
        parts.append(str(category).strip())
    color = item.get("color")
    if color:
        parts.append(str(color).strip())
    raw_style = item.get("styleTags")
    if raw_style:
        try:
            if isinstance(raw_style, str):
                parsed = json.loads(raw_style)
                if isinstance(parsed, list):
                    parts.extend(str(s) for s in parsed if s)
            elif isinstance(raw_style, list):
                parts.extend(str(s) for s in raw_style if s)
        except (ValueError, TypeError):
            pass
    return " ".join(parts) if parts else ""


async def _batch_encode_texts(embed_client, texts: list[str]) -> list[list[float] | None]:
    """批量编码文本向量，单条失败不影响整体

    Returns:
        向量列表（与 texts 等长，失败的为 None）
    """
    async def _safe_encode(text: str) -> list[float] | None:
        try:
            return await embed_client.encode_text(text)
        except Exception as e:
            logger.warning("[趋势工具] 编码文本失败: %s, text=%s", e, text[:80])
            return None

    tasks = [_safe_encode(text) for text in texts]
    return await asyncio.gather(*tasks)


def _kmeans_cosine(
    vectors: list[list[float]],
    items: list[dict],
    k: int,
    max_iter: int = 10,
) -> list[list[dict]]:
    """基于余弦相似度的简单 K-means 聚类

    Args:
        vectors: 向量列表（1024 维）
        items: 与 vectors 等长的商品列表
        k: 聚类数
        max_iter: 最大迭代次数

    Returns:
        长度为 k 的列表，每个元素是该簇的商品列表
    """
    import random
    n = len(vectors)
    if n <= k:
        # 样本数 ≤ k 时，每个样本一个簇
        return [[items[i]] for i in range(n)] + [[] for _ in range(k - n)]

    # 1. 随机选 k 个初始中心点
    indices = random.sample(range(n), k)
    centroids = [vectors[i][:] for i in indices]

    # 2. 迭代分配 + 更新中心
    assignments = [0] * n
    for _ in range(max_iter):
        changed = False
        # 分配阶段
        for i, vec in enumerate(vectors):
            best_cluster = 0
            best_sim = -1.0
            for c_idx, centroid in enumerate(centroids):
                sim = _cosine_similarity(vec, centroid)
                if sim > best_sim:
                    best_sim = sim
                    best_cluster = c_idx
            if assignments[i] != best_cluster:
                assignments[i] = best_cluster
                changed = True
        if not changed:
            break
        # 更新阶段：每个簇的向量平均
        for c_idx in range(k):
            members = [vectors[i] for i in range(n) if assignments[i] == c_idx]
            if members:
                dim = len(members[0])
                centroid = [0.0] * dim
                for vec in members:
                    for d in range(dim):
                        centroid[d] += vec[d]
                for d in range(dim):
                    centroid[d] /= len(members)
                centroids[c_idx] = centroid

    # 3. 按 cluster 收集 items
    clusters: list[list[dict]] = [[] for _ in range(k)]
    for i, c_idx in enumerate(assignments):
        clusters[c_idx].append(items[i])
    return clusters


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算余弦相似度"""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _extract_style_features(items: list[dict]) -> list[str]:
    """从商品列表中提取风格特征（基于品类/颜色/名称关键词）"""
    features: list[str] = []
    # 统计品类
    categories = [it.get("category", "") for it in items if it.get("category")]
    if categories:
        from collections import Counter
        cat_counter = Counter(categories)
        top_cat = cat_counter.most_common(1)[0][0]
        features.append(f"主品类:{top_cat}")
    # 统计颜色（从名称中提取关键词）
    color_keywords = ["白", "黑", "灰", "蓝", "红", "绿", "黄", "粉", "棕", "米", "卡其"]
    name_text = " ".join(it.get("name", "") for it in items)
    found_colors = [c for c in color_keywords if c in name_text]
    if found_colors:
        from collections import Counter
        color_counter = Counter()
        for c in found_colors:
            color_counter[c] = name_text.count(c)
        top_color = color_counter.most_common(1)[0][0]
        features.append(f"主色:{top_color}")
    # 风格关键词
    style_keywords = {
        "简约": ["简约", "基础", "纯色", "素色"],
        "休闲": ["休闲", "宽松", "舒适"],
        "商务": ["商务", "通勤", "正装", "西装"],
        "运动": ["运动", "卫衣", "跑步"],
        "复古": ["复古", "怀旧", "古着"],
        "街头": ["街头", "潮流", "嘻哈"],
    }
    for style, keywords in style_keywords.items():
        if any(kw in name_text for kw in keywords):
            features.append(style)
            break
    return features[:5]  # 最多 5 个特征


def _generate_style_name(cluster_idx: int, features: list[str]) -> str:
    """根据特征生成风格名称"""
    if not features:
        return f"风格簇 {cluster_idx + 1}"
    # 取前 2 个特征拼接
    return "+".join(features[:2])


def format_trend_hint_for_llm(trend_data: dict) -> str:
    """把趋势结果格式化为 LLM 可读的提示文本

    用于注入 select_top_outfits 的 prompt 上下文
    """
    if not trend_data or not trend_data.get("trending_styles"):
        return ""

    styles = trend_data["trending_styles"]
    category = trend_data.get("category", "")
    lines = [
        f"【流行趋势参考】（基于平台近 {trend_data.get('lookback_days', 30)} 天销量数据）",
        f"品类: {category or '全品类'}",
    ]
    for i, style in enumerate(styles[:3], 1):
        features = ", ".join(style.get("key_features", []))
        reps = style.get("representative_items", [])
        rep_names = ", ".join(r.get("name", "")[:15] for r in reps[:2])
        lines.append(
            f"{i}. {style['style_name']}（热度分 {style['score']:.2f}，"
            f"包含 {style['item_count']} 件热销商品）"
        )
        if features:
            lines.append(f"   特征: {features}")
        if rep_names:
            lines.append(f"   代表商品: {rep_names}")
    lines.append("请在 Top3 选择时适当参考流行趋势，但优先满足用户意图。")
    return "\n".join(lines)
