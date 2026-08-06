"""
统一工具注册表（ai-outfit + ai-models 共享）

工具清单：
- weather: 天气/季节查询（uapis.cn API）
- trending_styles: 流行趋势查询（基于平台销量数据）
- inventory: 实时库存批量查询（item-service）
- price_balance: 价格平衡分析（本地实现）
"""
from shared.tools.registry import (
    ToolDefinition,
    register,
    call_with_check,
    list_enabled,
)

__all__ = [
    "ToolDefinition",
    "register",
    "call_with_check",
    "list_enabled",
]
