"""
实时库存查询工具

用途：批量查询商品实时库存，避免推荐缺货商品搭配
接入环节：节点2 qdrant_search 输出后过滤候选 + 节点3 outfit_combination 最终校验

调用链路：
    Python ai-outfit → Java item-service POST /items/internal/inventory/batch

设计原则：
1. 复用 JavaClient 的 Nacos 服务发现 + user-info 透传
2. 失败时降级为"不过滤"（返回所有 item_id，由调用方原逻辑处理）
3. 走 Redis 缓存（5 分钟 TTL）减少 item-service 压力
"""
import logging

logger = logging.getLogger(__name__)


# 库存缓存 TTL（秒）—— 与 Java 侧 CacheClient 保持一致
_STOCK_CACHE_TTL = 300
# 缓存 key 前缀
_STOCK_CACHE_PREFIX = "ai:stock:"


async def batch_query_stock(java_client, item_ids: list[int], redis=None) -> dict[int, int]:
    """批量查询商品实时库存

    Args:
        java_client: shared.java_client.JavaClient 实例（已注入 Nacos 发现）
        item_ids: 商品 ID 列表
        redis: 可选的 Redis 客户端（aioredis），启用缓存

    Returns:
        {item_id: stock_quantity}，例：{101: 50, 102: 0, 103: 120}
        查询失败时返回空 dict（调用方应降级为不过滤）
    """
    if not item_ids:
        return {}

    result: dict[int, int] = {}
    missed_ids: list[int] = []

    # 1. 先查 Redis 缓存（如果 redis 可用）
    if redis is not None:
        try:
            cache_keys = [f"{_STOCK_CACHE_PREFIX}{iid}" for iid in item_ids]
            cached = await redis.mget(cache_keys)
            for iid, val in zip(item_ids, cached):
                if val is not None:
                    try:
                        result[iid] = int(val)
                    except (TypeError, ValueError):
                        missed_ids.append(iid)
                else:
                    missed_ids.append(iid)
        except Exception as e:
            logger.warning("[库存工具] Redis 缓存读取失败（降级直查）: %s", e)
            missed_ids = list(item_ids)
    else:
        missed_ids = list(item_ids)

    # 2. 缓存未命中的查 item-service
    if not missed_ids:
        logger.info("[库存工具] 全部命中缓存: %d 件商品", len(item_ids))
        return result

    try:
        # 复用 JavaClient._call（带 Nacos 发现 + user-info 头透传）
        # 路径：POST /items/internal/inventory/batch，body: {"itemIds": [101, 102]}
        # 注：/items/internal/** 已在网关层禁止外部访问，仅供微服务间调用
        resp = await java_client._call(
            "item-service", "POST", "/items/internal/inventory/batch",
            json={"itemIds": missed_ids},
        )
        if resp is None:
            logger.warning("[库存工具] item-service 不可用，降级为不过滤")
            return {}
        if resp.status_code != 200:
            logger.warning("[库存工具] 查询失败: status=%s, body=%s",
                           resp.status_code, resp.text[:200] if resp.text else "")
            return {}

        data = resp.json()
        # 兼容包装格式 {code:200, data:{...}} 与裸 dict
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
            data = data["data"]
        if not isinstance(data, dict):
            logger.warning("[库存工具] 返回格式异常: %s", type(data).__name__)
            return {}

        # 转换为 {int: int}
        for k, v in data.items():
            try:
                result[int(k)] = int(v)
            except (TypeError, ValueError):
                continue

        # 3. 回填 Redis 缓存（如果 redis 可用）
        if redis is not None:
            try:
                pipe = redis.pipeline()
                for iid in missed_ids:
                    stock = result.get(iid, 0)
                    pipe.set(f"{_STOCK_CACHE_PREFIX}{iid}", stock, ex=_STOCK_CACHE_TTL)
                await pipe.execute()
            except Exception as e:
                logger.warning("[库存工具] Redis 缓存回填失败（不影响主流程）: %s", e)

        logger.info("[库存工具] 查询成功: %d 件商品（缓存命中 %d，回源 %d），%d 件有库存",
                    len(item_ids), len(item_ids) - len(missed_ids), len(missed_ids),
                    sum(1 for s in result.values() if s > 0))
        return result

    except Exception as e:
        logger.warning("[库存工具] 查询异常，降级为不过滤: %s", e)
        return {}


async def filter_instock_items(
    java_client,
    item_ids: list[int],
    threshold: int = 0,
    redis=None,
) -> tuple[list[int], list[int], dict[int, int]]:
    """过滤出有库存的商品

    Args:
        java_client: JavaClient 实例
        item_ids: 待过滤的商品 ID 列表
        threshold: 库存阈值（默认 0，即必须 >0 才算有库存）
        redis: 可选的 Redis 客户端（aioredis），透传给 batch_query_stock

    Returns:
        (instock_ids, outstock_ids, stock_map)
        - instock_ids: 有库存的商品 ID 列表
        - outstock_ids: 缺货的商品 ID 列表
        - stock_map: {item_id: stock} 完整查询结果（供调用方记录日志）

        查询失败时：instock_ids = item_ids（降级为不过滤），outstock_ids = []
    """
    if not item_ids:
        return [], [], {}

    stock_map = await batch_query_stock(java_client, item_ids, redis=redis)

    # 查询失败或成功但空 → 降级为不过滤
    # 注：stock_map 为空可能是查询失败（item-service 不可用/异常）或成功但全部无库存，
    # 两种场景都无法可靠过滤，统一降级为不过滤，由调用方原逻辑处理
    if not stock_map:
        logger.warning(
            "[库存工具] stock_map 为空，降级为不过滤（可能是查询失败或全部无库存），item_ids=%s",
            item_ids[:20],
        )
        return list(item_ids), [], {}

    instock = [iid for iid in item_ids if stock_map.get(iid, 0) > threshold]
    outstock = [iid for iid in item_ids if stock_map.get(iid, 0) <= threshold]
    return instock, outstock, stock_map
