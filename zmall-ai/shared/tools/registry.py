"""
统一工具注册表（跨服务共享：ai-outfit + ai-models）

设计原则：
1. 所有外部工具（天气/库存/趋势/价格平衡等）在此统一注册
2. 每个工具独立开关 + 超时 + 降级值，失败不阻塞主流程
3. 自动熔断：连续失败 N 次后自动禁用 M 分钟
4. 对调用方透明：业务代码只关心 tool_name + args，不关心工具实现方式（HTTP/MCP/本地）

使用方式：
    from shared.tools.registry import call_with_check, list_enabled

    # 列出已启用工具
    enabled = list_enabled()
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

# v6 工具调用 Prometheus 指标（在调用入口埋点，监控工具健康度）
try:
    from shared.metrics import record_tool_call, set_tool_circuit_open
    _METRICS_AVAILABLE = True
except ImportError:
    # ai-models 等服务暂未引入 shared.metrics 时不阻塞工具注册
    _METRICS_AVAILABLE = False

    def record_tool_call(tool, status, duration_seconds=None):
        pass

    def set_tool_circuit_open(tool, is_open):
        pass

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    executor: Callable[[dict], Awaitable[dict]]
    enabled: bool = True
    timeout: float = 5.0
    fallback: Any = None  # 失败降级值（如 {}、{"season": "unknown"}）
    failure_threshold: int = 3  # 连续失败 N 次后熔断
    recovery_minutes: int = 5  # 熔断恢复时间（分钟）


@dataclass
class _ToolRuntime:
    """工具运行时状态（独立于 ToolDefinition，跟踪失败计数和熔断状态）"""
    failure_count: int = 0
    disabled_until: float = 0.0  # 0 表示未熔断；>0 表示熔断恢复时间戳


# 全局工具注册表：name -> ToolDefinition
_REGISTRY: dict[str, ToolDefinition] = {}
# 全局运行时状态表：name -> _ToolRuntime
_RUNTIME: dict[str, _ToolRuntime] = {}


def register(tool: ToolDefinition) -> None:
    """注册一个工具

    Args:
        tool: 工具定义
    """
    _REGISTRY[tool.name] = tool
    _RUNTIME[tool.name] = _ToolRuntime()
    logger.info("[ToolRegistry] 已注册工具: %s (enabled=%s, timeout=%ss)",
                tool.name, tool.enabled, tool.timeout)


def list_enabled() -> list[str]:
    """列出所有已启用（且未被熔断）的工具名"""
    now = time.time()
    enabled = []
    for name, tool in _REGISTRY.items():
        if not tool.enabled:
            continue
        rt = _RUNTIME.get(name)
        if rt and rt.disabled_until > now:
            continue  # 熔断中
        enabled.append(name)
    return enabled


async def call_with_check(
    tool_name: str,
    coro,
    fallback=None,
    timeout: float = 5.0,
) -> dict:
    """对一次性协程做"启用检查 + 超时 + 失败降级"

    用于节点内动态调用工具（executor 需要异步获取 java_client 等依赖时使用）

    Args:
        tool_name: 工具名（必须在 _REGISTRY 中注册过，用于开关检查）
        coro: 已构造的协程对象（awaitable）
        fallback: 失败降级值
        timeout: 超时秒数

    Returns:
        工具返回结果 dict；失败时返回 fallback
    """
    tool = _REGISTRY.get(tool_name)
    if not tool:
        record_tool_call(tool_name, "error")
        return fallback if fallback is not None else {"error": f"工具 {tool_name} 未注册"}

    if not tool.enabled:
        logger.info("[ToolRegistry] 工具 %s 已禁用，使用降级值", tool_name)
        record_tool_call(tool_name, "disabled")
        return fallback if fallback is not None else tool.fallback

    rt = _RUNTIME.get(tool_name)
    if rt:
        now = time.time()
        if rt.disabled_until > now:
            logger.info("[ToolRegistry] 工具 %s 熔断中，使用降级值", tool_name)
            record_tool_call(tool_name, "circuit_open")
            return fallback if fallback is not None else tool.fallback
        # 熔断恢复期：清零失败计数
        if rt.disabled_until > 0 and rt.disabled_until <= now:
            rt.disabled_until = 0.0
            rt.failure_count = 0
            logger.info("[ToolRegistry] 工具 %s 熔断恢复，重新启用", tool_name)

    start_ts = time.time()
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        if rt:
            was_fusing = rt.disabled_until > 0
            rt.failure_count = 0
            if was_fusing:
                rt.disabled_until = 0.0
                set_tool_circuit_open(tool_name, False)
        record_tool_call(tool_name, "success", time.time() - start_ts)
        return result
    except asyncio.TimeoutError:
        logger.warning("[ToolRegistry] 工具 %s 超时（%ss）", tool_name, timeout)
        if rt:
            rt.failure_count += 1
            if rt.failure_count >= tool.failure_threshold:
                rt.disabled_until = time.time() + tool.recovery_minutes * 60
                logger.warning("[ToolRegistry] 工具 %s 连续失败 %d 次，熔断 %d 分钟",
                               tool_name, rt.failure_count, tool.recovery_minutes)
                set_tool_circuit_open(tool_name, True)
        record_tool_call(tool_name, "timeout", time.time() - start_ts)
        return fallback if fallback is not None else tool.fallback
    except Exception as e:
        logger.warning("[ToolRegistry] 工具 %s 执行失败: %s", tool_name, e)
        if rt:
            rt.failure_count += 1
            if rt.failure_count >= tool.failure_threshold:
                rt.disabled_until = time.time() + tool.recovery_minutes * 60
                set_tool_circuit_open(tool_name, True)
        record_tool_call(tool_name, "error", time.time() - start_ts)
        return fallback if fallback is not None else tool.fallback
