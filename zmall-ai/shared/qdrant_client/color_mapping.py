"""Normalize color values shared by intent parsing and Qdrant reranking."""

from collections.abc import Iterable


_COLOR_ALIASES = {
    "black": "黑色",
    "white": "白色",
    "red": "红色",
    "orange": "橙色",
    "yellow": "黄色",
    "green": "绿色",
    "cyan": "青色",
    "teal": "青色",
    "blue": "蓝色",
    "purple": "紫色",
    "pink": "粉色",
    "gray": "灰色",
    "grey": "灰色",
    "brown": "棕色",
    "khaki": "卡其色",
    "beige": "米色",
    "multicolor": "花色",
    "patterned": "花色",
    "gold": "金色",
    "silver": "银色",
}


def normalize_color_values(value: object) -> list[str]:
    """Flatten color values, map common English aliases to catalog Chinese, dedupe."""
    if isinstance(value, str):
        values: Iterable[object] = [value]
    elif isinstance(value, Iterable):
        values = value
    else:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        if isinstance(item, (list, tuple, set)):
            candidates = normalize_color_values(item)
        elif item is None:
            candidates = []
        else:
            raw = str(item).strip()
            candidates = [_COLOR_ALIASES.get(raw.casefold(), raw)] if raw else []

        for color in candidates:
            key = color.casefold()
            if key not in seen:
                seen.add(key)
                normalized.append(color)
    return normalized
