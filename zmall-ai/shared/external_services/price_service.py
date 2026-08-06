"""
价格平衡工具（本地实现，无外部依赖）

用途：分析候选搭配商品的价格分布，给出平衡性评分和建议
接入环节：节点3 outfit_combination → LLM select_top_outfits 前作为约束条件

设计原则：
1. 纯本地计算（statistics 模块），无外部 API 依赖，几乎不会失败
2. 平衡分基于"最高价/最低价"倍数：
   - 倍数 ≤2：满分 1.0（价格相近，搭配合理）
   - 倍数 2-5：线性衰减
   - 倍数 ≥5：低分（避免 100 元上装配 5000 元下装）
3. 输出可读建议，LLM 可直接作为参考
"""
import logging
import statistics

logger = logging.getLogger(__name__)


# 价格倍数阈值（可由 config 覆盖）
_DEFAULT_RATIO_MAX = 5.0  # 倍数 ≥5 视为不平衡
_RATIO_FULL_SCORE = 2.0   # 倍数 ≤2 满分


async def analyze_price_balance(
    items: list[dict],
    ratio_max: float = _DEFAULT_RATIO_MAX,
) -> dict:
    """分析商品列表的价格平衡性

    Args:
        items: 商品列表，每个商品需含 price 字段（单位：分，与 ItemDTO.price 一致）
               例：[{"price": 9900, "category": "上衣"}, {"price": 29900, "category": "下装"}]
        ratio_max: 价格倍数阈值，超过此值视为不平衡

    Returns:
        {
            "balance_score": 0.85,        # 0-1，越高越平衡
            "price_range": [9900, 29900], # [min, max]
            "median_price": 19900,
            "ratio": 3.02,                # max/min
            "suggestion": "价格差距较大（3.0倍），可考虑增加中等价位商品平衡",
            "item_count": 2,
        }
    """
    if not items:
        return {
            "balance_score": 0.5,
            "price_range": [0, 0],
            "median_price": 0,
            "ratio": 1.0,
            "suggestion": "无商品数据",
            "item_count": 0,
        }

    # 提取价格（过滤 None/0）
    prices = [int(it.get("price") or 0) for it in items if it.get("price")]
    if not prices:
        return {
            "balance_score": 0.5,
            "price_range": [0, 0],
            "median_price": 0,
            "ratio": 1.0,
            "suggestion": "商品无价格数据",
            "item_count": len(items),
        }

    min_p = min(prices)
    max_p = max(prices)
    median_p = statistics.median(prices)

    # 计算倍数（避免除零）
    ratio = (max_p / min_p) if min_p > 0 else 1.0

    # 计算平衡分
    if ratio <= _RATIO_FULL_SCORE:
        score = 1.0
    elif ratio >= ratio_max:
        score = 0.0
    else:
        # 线性衰减：2-5 倍之间从 1.0 衰减到 0.0
        score = 1.0 - (ratio - _RATIO_FULL_SCORE) / (ratio_max - _RATIO_FULL_SCORE)
        score = max(0.0, min(1.0, score))

    suggestion = _build_suggestion(min_p, max_p, ratio, score, median_p)

    return {
        "balance_score": round(score, 3),
        "price_range": [min_p, max_p],
        "median_price": median_p,
        "ratio": round(ratio, 2),
        "suggestion": suggestion,
        "item_count": len(items),
    }


def _build_suggestion(min_p: int, max_p: int, ratio: float,
                      score: float, median: float) -> str:
    """构造人类可读的价格平衡建议"""
    # 价格转元（ItemDTO.price 单位是分）
    min_yuan = min_p / 100
    max_yuan = max_p / 100
    median_yuan = median / 100

    if ratio > 5:
        return (f"价格差距过大（{min_yuan:.0f}-{max_yuan:.0f}元，{ratio:.1f}倍），"
                f"建议搭配价格相近的商品，避免悬殊搭配")
    elif ratio > 3:
        return (f"价格差距较大（{ratio:.1f}倍，{min_yuan:.0f}-{max_yuan:.0f}元），"
                f"可考虑增加中等价位（约{median_yuan:.0f}元）商品平衡")
    elif ratio > 2:
        return (f"价格搭配尚可（{ratio:.1f}倍，{min_yuan:.0f}-{max_yuan:.0f}元），"
                f"整体合理")
    else:
        return f"价格搭配合理（{min_yuan:.0f}-{max_yuan:.0f}元，差距≤2倍）"


def format_price_hint_for_llm(price_balance: dict) -> str:
    """把价格平衡结果格式化为 LLM 可读的提示文本

    用于注入 select_top_outfits 的 prompt 上下文
    """
    if not price_balance or price_balance.get("balance_score") is None:
        return ""

    score = price_balance.get("balance_score", 0.5)
    suggestion = price_balance.get("suggestion", "")
    ratio = price_balance.get("ratio", 1.0)
    price_range = price_balance.get("price_range", [0, 0])

    if not price_range or price_range[0] == 0:
        return ""

    min_yuan = price_range[0] / 100
    max_yuan = price_range[1] / 100

    return (
        f"【价格平衡分析】\n"
        f"- 候选商品价格区间: {min_yuan:.0f}-{max_yuan:.0f}元\n"
        f"- 最高/最低价倍数: {ratio:.1f}倍\n"
        f"- 平衡分: {score:.2f}（0-1，越高越平衡）\n"
        f"- 建议: {suggestion}\n"
        f"请在 Top3 选择时优先挑选价格搭配合理的组合，避免高低价悬殊搭配。"
    )
