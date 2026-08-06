"""
ai-outfit 工具注册入口

启动时调用 register_outfit_tools()，注册所有外部工具的元数据（开关/超时/降级值）。
节点内通过 call_with_check("工具名", coro_factory()) 调用，享受统一熔断/超时/降级。

设计原则：
1. 注册阶段不获取 java_client 等异步依赖（启动期与运行期解耦）
2. executor 留空（None），实际调用通过 call_with_check 传入协程
3. 每个工具的 fallback 提供合理的降级值，主流程不阻塞
"""
import logging

from app.core.config import settings
from shared.tools.registry import ToolDefinition, register, list_enabled

logger = logging.getLogger(__name__)


def register_outfit_tools() -> None:
    """注册 ai-outfit 所有外部工具

    在 FastAPI lifespan 启动阶段调用一次。
    重复调用安全（register 会覆盖旧定义）。
    """
    # 工具总开关：关闭时所有工具 enabled=False
    master_enabled = settings.external_tools_enabled

    # ===== 价格平衡工具（本地实现，默认开）=====
    register(ToolDefinition(
        name="price_balance",
        description="分析候选搭配商品的价格平衡性，返回 0-1 分数和建议",
        executor=_no_op_executor,  # 实际调用通过 call_with_check
        enabled=master_enabled and settings.price_tool_enabled,
        timeout=1.0,
        fallback={"balance_score": 0.5, "suggestion": "", "price_range": [0, 0]},
        failure_threshold=3,
        recovery_minutes=5,
    ))

    # ===== 库存查询工具（HTTP 调 item-service）=====
    register(ToolDefinition(
        name="inventory",
        description="批量查询商品实时库存，避免推荐缺货商品",
        executor=_no_op_executor,
        enabled=master_enabled and settings.inventory_tool_enabled,
        timeout=3.0,
        fallback={},  # 空 dict 表示降级为不过滤
        failure_threshold=3,
        recovery_minutes=5,
    ))

    # ===== 流行趋势工具（HTTP + Jina 编码 + 聚类，旧版基于平台销量）=====
    # 已被 fashion_trend 替代，保留注册仅为向后兼容（默认关闭）
    register(ToolDefinition(
        name="trending_styles",
        description="查询某品类的流行风格（基于平台销量数据 + 向量聚类，旧版，已被 fashion_trend 替代）",
        executor=_no_op_executor,
        enabled=master_enabled and settings.trend_tool_enabled,
        timeout=10.0,  # Jina 编码 + 聚类较慢
        fallback={"trending_styles": [], "error": "disabled"},
        failure_threshold=2,  # 趋势工具失败 2 次即熔断（成本高）
        recovery_minutes=10,
    ))

    # ===== 时尚潮流搜索工具（HTTP 调 AnySearch API）=====
    # 数据源：social_media.social_media + general.general 两个 tag 并行搜索
    # 根据用户 city/country 路由不同地区的搜索关键词（中国搜小红书、日本搜原宿風等）
    register(ToolDefinition(
        name="fashion_trend",
        description="查询用户所在地区的实时时尚潮流信息（基于 AnySearch API，社媒+通用搜索）",
        executor=_no_op_executor,
        enabled=master_enabled and settings.fashion_trend_tool_enabled,
        timeout=12.0,  # 两个 tag 并行搜索，海外服务走代理，留足超时
        fallback={"merged_results": [], "error": "disabled", "data_source": "anysearch_api"},
        failure_threshold=3,
        recovery_minutes=5,
    ))

    # ===== 天气工具（HTTP 调 uapis.cn API）=====
    register(ToolDefinition(
        name="weather",
        description="查询用户所在地天气和季节，给搭配推荐提供季节约束",
        executor=_no_op_executor,
        enabled=master_enabled and settings.weather_tool_enabled,
        timeout=5.0,
        fallback=None,  # 节点内会特殊处理（降级为月份推断）
        failure_threshold=3,
        recovery_minutes=5,
    ))

    enabled = list_enabled()
    logger.info("[ToolRegistry] ai-outfit 工具注册完成: %s", enabled)


async def _no_op_executor(args: dict) -> dict:
    """占位 executor（实际调用通过 call_with_check 传入协程）

    注册时必须提供 executor 函数（dataclass 必填字段），但实际不会调用。
    节点内通过 call_with_check("工具名", real_coro) 调用真实业务逻辑。
    """
    return {"error": "应通过 call_with_check 调用"}
