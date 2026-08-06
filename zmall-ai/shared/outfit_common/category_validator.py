"""AI 随心搭品类组合校验（商品驱动模式 ai-models + 风格驱动模式 ai-outfit 共用）

抽自 ai-outfit/app/api/outfit_agent.py 和 ai-outfit/app/services/agent_service.py
原本只有注释"前端约束"无后端校验的技术债。

业务规则：
- 同品类只能选 1 件（上衣/下装/全身套装/鞋/帽子/包/配饰互斥）
- 全身套装与上衣/下装互斥（全身套装已覆盖上下身，叠加穿会破坏 VTON 效果）
- 全局上限 5 件（含四类来源合计：风格驱动 categories + 衣橱/购物车/订单/搜索）

链式 VTON 件数影响：
- 互斥前最坏 5 件 VTON（上衣+下装+全身套装+帽+鞋）= 5×85s ≈ 425s
- 互斥后最多 3 件 VTON（全身套装+鞋+帽子 或 上衣+下装+鞋）= 3×85s ≈ 255s
- 超时阈值据此动态计算：见 estimate_vton_timeout()
"""
import logging
from typing import Iterable

logger = logging.getLogger(__name__)

# 所有支持的服装品类（与 nodes.VTON_CATEGORIES + WAN_ACCESSORY_CATEGORIES 对齐）
ALL_OUTFIT_CATEGORIES = ("上衣", "下装", "全身套装", "鞋", "帽子", "包", "配饰")

# VTON 支持的品类（千问 aitryon-plus，走链式 VTON）
# 2026-08-06 调整：鞋/帽子从 VTON 移出（aitryon-plus 仅支持衣物换装，
# top_garment_url 是"上装"语义，把鞋/帽子塞进去接口虽返回成功但生成图中不含该单品）
# → 改走 wan2.7-image 图生图穿戴；下装（裤子/裙子）原生支持 bottom_garment_url，保留 VTON
VTON_CATEGORIES = ("上衣", "下装", "全身套装")

# wan2.7-image 穿戴的品类（VTON 不支持，走图生图）
WAN_ACCESSORY_CATEGORIES = ("鞋", "包", "帽子", "配饰")

# 全局上限（含风格驱动 categories + 衣橱/购物车/订单/搜索合计）
MAX_ITEMS_PER_OUTFIT = 5

# 全身套装与上衣/下装互斥的冲突组
# 业务含义：全身套装 = 连衣裙/旗袍等连体款，本身已覆盖上下身，
# 叠加上衣/下装会破坏 VTON 渲染（全身套装覆盖上衣/下装，产生错位）
DRESS_CONFLICT_GROUPS = (
    ("全身套装", "上衣"),
    ("全身套装", "下装"),
)


class CategoryConflictError(ValueError):
    """品类组合冲突异常

    Attributes:
        conflict_type: 冲突类型（duplicate / dress_conflict / exceed_limit）
        details: 冲突详情（具体冲突的品类或超限数）
    """

    def __init__(self, conflict_type: str, details: str):
        self.conflict_type = conflict_type
        self.details = details
        super().__init__(details)


def validate_category_combination(categories: Iterable[str]) -> list[str]:
    """校验品类组合是否合法（去重 + 互斥检查）

    Args:
        categories: 品类列表（可能含重复或冲突项）

    Returns:
        去重后的品类列表（保持输入顺序）

    Raises:
        CategoryConflictError: 冲突时抛出
            - conflict_type="duplicate": 同品类重复（已自动去重，仅 warning 不抛异常）
            - conflict_type="dress_conflict": 全身套装与上衣/下装冲突
            - conflict_type="exceed_limit": 超过全局上限 5 件
    """
    if not categories:
        return []

    # 1. 去重（保持顺序）
    seen: set[str] = set()
    deduped: list[str] = []
    for cat in categories:
        if not cat:
            continue
        if cat in seen:
            logger.warning("品类重复，已自动去重: category=%s", cat)
            continue
        if cat not in ALL_OUTFIT_CATEGORIES:
            logger.warning("未知品类，跳过校验: category=%s", cat)
            continue
        seen.add(cat)
        deduped.append(cat)

    # 2. 全身套装与上衣/下装互斥检查
    for group in DRESS_CONFLICT_GROUPS:
        if all(c in seen for c in group):
            raise CategoryConflictError(
                conflict_type="dress_conflict",
                details=f"品类冲突：{group[0]} 与 {group[1]} 互斥（{group[0]}已覆盖上下身，"
                        f"请仅选其中之一）",
            )

    # 3. 全局上限检查
    if len(deduped) > MAX_ITEMS_PER_OUTFIT:
        raise CategoryConflictError(
            conflict_type="exceed_limit",
            details=f"品类数超过上限：{len(deduped)} > {MAX_ITEMS_PER_OUTFIT}（最多 {MAX_ITEMS_PER_OUTFIT} 件）",
        )

    return deduped


def filter_conflicting_categories(categories: Iterable[str]) -> list[str]:
    """LLM 决策兜底：自动剔除冲突品类（不抛异常）

    用于节点3 LLM 决策后的兜底处理：
    - 如果 LLM 同时返回了"全身套装"+"上衣"/"下装"，保留先出现的，剔除冲突项
    - 同品类去重
    - 超限时截断到上限

    Args:
        categories: LLM 返回的品类列表

    Returns:
        合法化的品类列表（去重 + 剔除冲突 + 截断）
    """
    if not categories:
        return []

    seen: set[str] = set()
    result: list[str] = []
    has_dress = False
    has_top_or_bottom = False

    for cat in categories:
        if not cat or cat not in ALL_OUTFIT_CATEGORIES:
            continue
        if cat in seen:
            continue

        # 全身套装与上衣/下装互斥：先到先得
        if cat == "全身套装":
            if has_top_or_bottom:
                logger.warning("[品类兜底] 已有上衣/下装，剔除全身套装: %s", result)
                continue
            has_dress = True
        elif cat in ("上衣", "下装"):
            if has_dress:
                logger.warning("[品类兜底] 已有全身套装，剔除 %s: %s", cat, result)
                continue
            has_top_or_bottom = True

        seen.add(cat)
        result.append(cat)

        if len(result) >= MAX_ITEMS_PER_OUTFIT:
            break

    return result


# ============================================================================
# 动态超时阈值计算
# ============================================================================

# 单件 VTON 平均耗时（基于生产日志统计：84-87s，取保守值 90s）
VTON_PER_ITEM_SECONDS = 90

# 非VTON 节点总耗时（intent + search + outfit + reflection + upload + 阶段一 upload）
# 基于生产日志：节点1 ~11s + 节点2 ~3s + 节点3 ~10s + 节点3.5 ~10s + 节点5 ~1s ≈ 35s
NON_VTON_NODE_SECONDS = 45

# 单件 VTON 内部最大轮询时间（vton_client.POLL_MAX_DURATION）
VTON_POLL_MAX_SECONDS = 180

# 最小/最大超时阈值边界
MIN_TIMEOUT_SECONDS = 120        # 至少 2 分钟（保证单件 VTON 能完成）
MAX_TIMEOUT_SECONDS = 600        # 最多 10 分钟（防止失败任务无限占用资源）


def estimate_vton_timeout(category_count: int) -> int:
    """根据品类件数动态估算 VTON 阶段超时阈值

    业务场景：
    - 1 件 VTON（如仅上衣）：90s + 45s 缓冲 = 135s → 取 150s
    - 2 件 VTON（上衣+下装 或 全身套装+鞋）：180s + 45s = 225s
    - 3 件 VTON（上衣+下装+鞋 或 全身套装+鞋+帽子）：270s + 45s = 315s
    - 5 件 VTON（互斥前最坏情况，不应出现但留兜底）：450s + 45s = 495s → 截断到 600s

    单件 VTON 内部已有 POLL_MAX_DURATION=180s 兜底，
    外层超时只需覆盖"N×单件耗时 + 非VTON节点耗时 + 20%缓冲"。

    Args:
        category_count: VTON 品类件数（不含配饰/包类，它们走 wan2.7-image 耗时较短）

    Returns:
        超时阈值秒数
    """
    if category_count <= 0:
        return MIN_TIMEOUT_SECONDS

    # 单件 VTON 最大耗时（含轮询兜底）
    # 注：实际平均 90s，但最坏情况会到 180s，取平均值更贴近实际
    # 用平均值而非最大值，避免超时阈值过大导致失败任务占用资源过久
    vton_total = category_count * VTON_PER_ITEM_SECONDS

    # 总耗时 = VTON + 非VTON节点 + 20% 缓冲（应对网络抖动/重试）
    estimated = (vton_total + NON_VTON_NODE_SECONDS) * 1.2

    # 边界约束
    timeout = max(MIN_TIMEOUT_SECONDS, min(int(estimated), MAX_TIMEOUT_SECONDS))

    logger.info(
        "动态超时估算: category_count=%d, vton_total=%ds, non_vton=%ds, "
        "estimated=%.0fs → timeout=%ds",
        category_count, vton_total, NON_VTON_NODE_SECONDS, estimated, timeout,
    )
    return timeout


def count_vton_categories(categories: Iterable[str]) -> int:
    """统计需要走 VTON 的品类数（排除配饰/包/鞋/帽子类，它们走 wan2.7-image）

    Args:
        categories: 品类列表

    Returns:
        VTON 品类数（上衣/下装/全身套装 的去重计数）
    """
    if not categories:
        return 0
    vton_set = {c for c in categories if c in VTON_CATEGORIES}
    return len(vton_set)
