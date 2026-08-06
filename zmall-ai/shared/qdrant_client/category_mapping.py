"""
品类中英文映射表（§3.8）

设计：
- 前端 / MQ 同步消息 / 日志：用中文（上衣/下装/全身套装/鞋/帽子/包/配饰）
- Qdrant payload.category：统一存英文枚举（tops/bottoms/dress/shoes/hat/bag/accessory）
- ai-outfit 在边界处做转码：节点2 检索前中→英，节点3 返回结果时英→中

全身套装说明：
- "全身套装" = 成套衣服/连衣裙/连体衣/旗袍等"一件即覆盖全身"的成套衣物
  （一次 VTON 完成全身换装，等价于 [上衣+下装]）
- 半身裙归为"下装"（category=bottoms），不归为"全身套装"

兼容性：
- 旧 Qdrant 数据可能 payload.category 是中文，searcher 检索时同时匹配中英文
"""
from typing import Iterable

# 中文 → 英文
CN_TO_EN: dict[str, str] = {
    "上衣": "tops",
    "下装": "bottoms",
    "全身套装": "dress",
    "鞋": "shoes",
    "帽子": "hat",
    "包": "bag",
    "配饰": "accessory",
}

# 英文 → 中文（反向映射）
EN_TO_CN: dict[str, str] = {v: k for k, v in CN_TO_EN.items()}


def to_en(category: str | None) -> str | None:
    """中文品类 → 英文枚举

    已是英文或 None 时原样返回（幂等）。
    未知中文返回原值（让 Qdrant 自然过滤，避免静默丢数据）。
    """
    if category is None:
        return None
    if category in CN_TO_EN:
        return CN_TO_EN[category]
    # 已是英文或未识别，原样返回
    return category


def to_cn(category: str | None) -> str | None:
    """英文枚举 → 中文品类

    已是中文或 None 时原样返回（幂等）。
    未知英文返回原值。
    """
    if category is None:
        return None
    if category in EN_TO_CN:
        return EN_TO_CN[category]
    return category


def to_en_list(categories: Iterable[str] | None) -> list[str]:
    """批量中→英（去 None，保持顺序）"""
    if not categories:
        return []
    return [to_en(c) for c in categories if c]


def to_cn_list(categories: Iterable[str] | None) -> list[str]:
    """批量英→中（去 None，保持顺序）"""
    if not categories:
        return []
    return [to_cn(c) for c in categories if c]


# 默认品类组合（英文，Qdrant payload 用）
DEFAULT_CATEGORIES_EN: list[str] = ["tops", "bottoms", "shoes"]

# 默认品类组合（中文，前端/API 用）
DEFAULT_CATEGORIES_CN: list[str] = ["上衣", "下装", "鞋"]
