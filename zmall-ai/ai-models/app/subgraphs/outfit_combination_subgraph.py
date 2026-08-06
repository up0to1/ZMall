"""
AI 模特多换装模式 - LLM 搭配推荐子 Agent（v4 新增）

功能：
- 输入商家选定的多件商品（可能含 2 件同类）
- LLM 推荐合法搭配组合（1-4 套）
- LLM 不可用时降级为笛卡尔积生成

与 Java 侧的对接：
- Java createModelGenerateTask 通过 HTTP 调用 /api/v1/model/outfit-combinations
- 也可在 Python 工作流内部直接调用（如 generation_mode 已确定但 combinations 未填充）
"""
import json
import logging

from app.core.config import settings
from app.subgraphs._llm import _call_llm_with_retry, LLM_PLAN_TIMEOUT, llm_cache
from app.prompts.outfit_combination_prompts import (
    OUTFIT_COMBINATION_SYSTEM_PROMPT,
    OUTFIT_COMBINATION_USER_PROMPT,
)

logger = logging.getLogger(__name__)

# 合法品类组合（与 OutfitCategories.java 保持一致）
_VALID_CATEGORY_STRUCTURES = [
    {"上衣"},
    {"下装"},
    {"全身套装"},
    {"帽子"},
    {"上衣", "下装"},
    {"上衣", "帽子"},
    {"下装", "帽子"},
    {"上衣", "下装", "帽子"},
    {"全身套装", "帽子"},
]

# 最大组合数（成本控制）
MAX_COMBINATIONS = 4


def _is_valid_combination(items: list[dict], item_ids: list[int]) -> bool:
    """校验单个组合是否为合法品类结构"""
    id_to_item = {it.get("itemId"): it for it in items}
    categories = set()
    for item_id in item_ids:
        item = id_to_item.get(item_id)
        if not item:
            return False
        categories.add(item.get("category", ""))
    # 全身套装与上衣/下装互斥
    if "全身套装" in categories and ("上衣" in categories or "下装" in categories):
        return False
    # 帽子最多 1 件（组合内不会出现重复 itemId，自然满足）
    return categories in _VALID_CATEGORY_STRUCTURES


def _generate_fallback_combinations(items: list[dict]) -> tuple[list[list[int]], list[str]]:
    """LLM 不可用时的降级：按规则生成合法组合（笛卡尔积 + 去重）

    策略：
    - 单件商品：直接作为 1 套
    - 多件商品：上装×下装 笛卡尔积，每套可加帽子
    - 限制 ≤ 4 套
    """
    if not items:
        return [], []

    tops = [it for it in items if it.get("category") == "上衣"]
    bottoms = [it for it in items if it.get("category") == "下装"]
    dresses = [it for it in items if it.get("category") == "全身套装"]
    hats = [it for it in items if it.get("category") == "帽子"]

    combinations: list[list[int]] = []
    reasons: list[str] = []

    # 全身套装优先单独成套
    for dress in dresses:
        if len(combinations) >= MAX_COMBINATIONS:
            break
        combo = [dress["itemId"]]
        # 全身套装可配 1 顶帽子
        if hats:
            combo.append(hats[0]["itemId"])
        combinations.append(combo)
        reasons.append(f"{dress.get('name', '全身套装')} 单独成套" + (" + 帽子点缀" if hats else ""))

    # 上装×下装 笛卡尔积
    if tops and bottoms:
        for top in tops:
            for bottom in bottoms:
                if len(combinations) >= MAX_COMBINATIONS:
                    break
                combo = [top["itemId"], bottom["itemId"]]
                if hats:
                    combo.append(hats[0]["itemId"])
                combinations.append(combo)
                reasons.append(
                    f"{top.get('name', '上装')} + {bottom.get('name', '下装')}"
                    + (" + 帽子" if hats else "")
                )

    # 仅有上装或仅有下装
    elif tops and not bottoms and not dresses:
        for top in tops:
            if len(combinations) >= MAX_COMBINATIONS:
                break
            combo = [top["itemId"]]
            if hats:
                combo.append(hats[0]["itemId"])
            combinations.append(combo)
            reasons.append(f"{top.get('name', '上装')} 单独展示" + (" + 帽子" if hats else ""))
    elif bottoms and not tops and not dresses:
        for bottom in bottoms:
            if len(combinations) >= MAX_COMBINATIONS:
                break
            combo = [bottom["itemId"]]
            if hats:
                combo.append(hats[0]["itemId"])
            combinations.append(combo)
            reasons.append(f"{bottom.get('name', '下装')} 单独展示" + (" + 帽子" if hats else ""))

    # 去重（保留顺序）
    seen = set()
    unique_combos = []
    unique_reasons = []
    for combo, reason in zip(combinations, reasons):
        key = tuple(sorted(combo))
        if key not in seen:
            seen.add(key)
            unique_combos.append(combo)
            unique_reasons.append(reason)

    return unique_combos[:MAX_COMBINATIONS], unique_reasons[:MAX_COMBINATIONS]


async def recommend_outfit_combinations(
    items: list[dict],
    use_llm: bool = True,
) -> tuple[list[list[int]], list[str]]:
    """推荐多套搭配组合

    Args:
        items: 商家选定的商品列表（含 itemId/category/name/color/styleTags）
        use_llm: 是否使用 LLM 推荐（False 时强制走规则降级）
    Returns:
        (combinations, reasons)
        - combinations: 1-4 套商品 ID 组合
        - reasons: 每套的推荐理由（与 combinations 等长）
    """
    if not items:
        return [], []

    # 商品数 ≤ 1 时直接返回单套
    if len(items) == 1:
        return [[items[0]["itemId"]]], [f"{items[0].get('name', '商品')} 单独展示"]

    # LLM 不可用或未配置时走规则降级
    if not use_llm or not _is_llm_configured():
        logger.info("[搭配推荐] LLM 不可用，走规则降级（笛卡尔积）")
        return _generate_fallback_combinations(items)

    # LLM 缓存：相同商品列表的推荐结果秒级返回
    cached = await llm_cache.get("outfit_combination", items, None)
    if cached is not None:
        logger.info("[搭配推荐] 命中缓存，秒级返回")
        return cached["combinations"], cached["reasons"]

    # 构造 LLM 输入（精简字段，降低 token 成本）
    items_for_llm = [
        {
            "itemId": it.get("itemId"),
            "category": it.get("category", ""),
            "name": it.get("name", ""),
            "color": it.get("color", ""),
            "styleTags": it.get("styleTags", []),
        }
        for it in items
    ]

    user_prompt = OUTFIT_COMBINATION_USER_PROMPT.format(
        items_json=json.dumps(items_for_llm, ensure_ascii=False),
    )

    llm_result = await _call_llm_with_retry(
        model=settings.llm_text_model,
        system_prompt=OUTFIT_COMBINATION_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        agent_name="outfit_combination",
        timeout=LLM_PLAN_TIMEOUT,
        temperature=0.3,
    )

    if llm_result.is_fallback or llm_result.data is None:
        logger.warning("[搭配推荐] LLM 调用失败，走规则降级")
        return _generate_fallback_combinations(items)

    # 解析 LLM 输出并校验合法性
    raw_combinations = llm_result.data.get("combinations") or []
    raw_reasons = llm_result.data.get("reasons") or []

    valid_combinations: list[list[int]] = []
    valid_reasons: list[str] = []
    seen = set()

    for idx, combo in enumerate(raw_combinations[:MAX_COMBINATIONS]):
        if not isinstance(combo, list):
            continue
        # 校验 itemId 都在原 items 中
        item_ids_set = {it.get("itemId") for it in items}
        if not all(iid in item_ids_set for iid in combo):
            logger.warning("[搭配推荐] LLM 输出含未知 itemId，跳过: %s", combo)
            continue
        # 校验品类结构合法
        if not _is_valid_combination(items, combo):
            logger.warning("[搭配推荐] LLM 输出品类结构非法，跳过: %s", combo)
            continue
        # 去重
        key = tuple(sorted(combo))
        if key in seen:
            continue
        seen.add(key)
        valid_combinations.append(combo)
        reason = raw_reasons[idx] if idx < len(raw_reasons) else ""
        valid_reasons.append(reason)

    # LLM 输出全非法 → 走规则降级
    if not valid_combinations:
        logger.warning("[搭配推荐] LLM 输出全部非法，走规则降级")
        return _generate_fallback_combinations(items)

    # 写入缓存
    await llm_cache.set(
        "outfit_combination", items, None,
        {"combinations": valid_combinations, "reasons": valid_reasons},
    )

    logger.info(
        "[搭配推荐] LLM 推荐成功: 商品数=%d, 组合数=%d",
        len(items), len(valid_combinations),
    )

    return valid_combinations, valid_reasons


def _is_llm_configured() -> bool:
    """检查 LLM 是否已配置"""
    return bool(
        settings.llm_api_url and settings.llm_api_key
        and settings.llm_text_model
    )
