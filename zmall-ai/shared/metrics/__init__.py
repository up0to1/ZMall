"""
Prometheus 监控指标定义（后端架构方案 §7.5 监控告警）

共享给 ai-models 与 ai-outfit 使用，统一指标命名规范：
  - ai_model_generate_total{status}            模特图生成计数
  - ai_model_generate_duration_seconds          模特图生成耗时分布
  - ai_outfit_generate_total{status, mode}     随心搭生成计数
  - ai_outfit_generate_duration_seconds         随心搭生成耗时分布
  - ai_agent_workflow_total{status, node}      LangGraph 节点执行计数
  - ai_agent_workflow_duration_seconds          LangGraph 工作流总耗时
  - ai_qdrant_memory_usage_bytes                Qdrant 内存使用量
  - ai_mq_consume_total{queue, status}         MQ 消费计数
  - ai_quota_check_total{type, result}         配额校验计数
  - ai_tool_call_total{tool, status}           v6 外部工具调用计数
  - ai_tool_call_duration_seconds{tool}        v6 外部工具调用耗时分布
  - ai_tool_circuit_state{tool, state}         v6 外部工具熔断状态

告警阈值参考：
  - ai_model_generate_duration_seconds_quantile{quantile="0.95"} > 30s
  - 模型失败率（FAILED / total）> 10%
  - Qdrant 内存使用 > 80%
  - ai_tool_circuit_state{state="open"} == 1 持续 5min 触发告警
"""
from prometheus_client import Counter, Histogram, Gauge


# ========== 模特图生成 ==========

MODEL_GENERATE_TOTAL = Counter(
    "ai_model_generate_total",
    "AI 模特图生成任务总数",
    ["status"],  # SUCCESS / FAILED / TIMEOUT
)

MODEL_GENERATE_DURATION = Histogram(
    "ai_model_generate_duration_seconds",
    "AI 模特图生成耗时分布（秒）",
    buckets=(1, 5, 10, 30, 60, 120, 300),
)


# ========== AI 随心搭（ai-models 商品驱动模式） ==========

OUTFIT_GENERATE_TOTAL = Counter(
    "ai_outfit_generate_total",
    "AI 随心搭生成任务总数",
    ["status", "mode"],  # status: SUCCESS/FAILED; mode: product/agent
)

OUTFIT_GENERATE_DURATION = Histogram(
    "ai_outfit_generate_duration_seconds",
    "AI 随心搭生成耗时分布（秒）",
    buckets=(1, 5, 10, 30, 60),
)


# ========== ai-outfit LangGraph 工作流 ==========

AGENT_WORKFLOW_TOTAL = Counter(
    "ai_agent_workflow_total",
    "ai-outfit LangGraph 工作流执行总数",
    ["status", "node"],  # status: SUCCESS/FAILED; node: intent/search/outfit/vton/upload
)

AGENT_WORKFLOW_DURATION = Histogram(
    "ai_agent_workflow_duration_seconds",
    "ai-outfit LangGraph 工作流总耗时（秒）",
    buckets=(1, 5, 10, 30, 60),
)


# ========== 节点级监控（测试可观测性）==========
# 用于定位 AI 随心搭哪个节点慢/失败，辅助单点和 JMeter 测试分析

AGENT_WORKFLOW_NODE_TOTAL = Counter(
    "ai_agent_workflow_node_total",
    "ai-outfit LangGraph 节点执行总数",
    ["status", "node"],  # status: SUCCESS/FAILED; node: intent/wardrobe/search/outfit/reflection/refine/vton/upload
)

AGENT_WORKFLOW_NODE_DURATION = Histogram(
    "ai_agent_workflow_node_duration_seconds",
    "ai-outfit LangGraph 节点耗时分布（秒）",
    ["node"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)


# ========== LLM 调用监控（测试可观测性）==========

LLM_CALL_TOTAL = Counter(
    "ai_llm_call_total",
    "LLM 调用总数",
    ["action", "status"],  # action: parse_note/hyde/analyze_photo/select_outfits/reflect/react_feedback/react_intent/react_decision/parse_feedback; status: success/failed
)

LLM_CALL_DURATION = Histogram(
    "ai_llm_call_duration_seconds",
    "LLM 调用耗时分布（秒）",
    ["action"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30),
)


# ========== VTON 调用监控（测试可观测性）==========

VTON_CALL_TOTAL = Counter(
    "ai_vton_call_total",
    "VTON 虚拟试衣调用总数",
    ["status", "stage"],  # status: success/failed; stage: create/poll/download/chain_item
)

VTON_CALL_DURATION = Histogram(
    "ai_vton_call_duration_seconds",
    "VTON 虚拟试衣调用耗时分布（秒）",
    buckets=(1, 5, 10, 30, 60, 120, 180),
)


def record_agent_workflow_node(node: str, status: str, duration_seconds: float):
    """记录 LangGraph 节点执行结果和耗时"""
    AGENT_WORKFLOW_NODE_TOTAL.labels(status=status, node=node).inc()
    AGENT_WORKFLOW_NODE_DURATION.labels(node=node).observe(duration_seconds)


def record_llm_call(action: str, status: str, duration_seconds: float | None = None):
    """记录 LLM 调用结果和耗时"""
    LLM_CALL_TOTAL.labels(action=action, status=status).inc()
    if duration_seconds is not None:
        LLM_CALL_DURATION.labels(action=action).observe(duration_seconds)


def record_vton_call(status: str, stage: str, duration_seconds: float | None = None):
    """记录 VTON 虚拟试衣调用结果和耗时"""
    VTON_CALL_TOTAL.labels(status=status, stage=stage).inc()
    if duration_seconds is not None:
        VTON_CALL_DURATION.observe(duration_seconds)


# ========== ai-models Agent 级 LLM 调用监控 ==========

_AGENT_LLM_CALLS = Counter(
    "ai_model_agent_llm_calls_total",
    "ai-models 多 Agent LLM 调用次数",
    ["agent", "status"],  # agent: stylist_eu_plan/lighting_review/...; status: success/fallback
)

_AGENT_LLM_DURATION = Histogram(
    "ai_model_agent_llm_duration_seconds",
    "ai-models 多 Agent LLM 调用耗时分布（秒）",
    ["agent"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60),
)

_AGENT_LLM_RETRIES = Counter(
    "ai_model_agent_llm_retries_total",
    "ai-models 多 Agent LLM 调用重试次数",
    ["agent"],
)

# ========== MQ 消费 ==========

MQ_CONSUME_TOTAL = Counter(
    "ai_mq_consume_total",
    "MQ 消费消息总数",
    ["queue", "status"],  # status: success/failed/idempotent_skip
)


# ========== 配额校验 ==========

QUOTA_CHECK_TOTAL = Counter(
    "ai_quota_check_total",
    "AI 配额校验次数",
    ["type", "result"],  # type: MODEL/OUTFIT_AGENT; result: ok/insufficient/failed
)


def record_model_generate(status: str, duration_seconds: float | None = None):
    """记录一次模特图生成结果"""
    MODEL_GENERATE_TOTAL.labels(status=status).inc()
    if duration_seconds is not None:
        MODEL_GENERATE_DURATION.observe(duration_seconds)


def record_outfit_generate(status: str, mode: str, duration_seconds: float | None = None):
    """记录一次随心搭生成结果"""
    OUTFIT_GENERATE_TOTAL.labels(status=status, mode=mode).inc()
    if duration_seconds is not None:
        OUTFIT_GENERATE_DURATION.observe(duration_seconds)


def record_agent_workflow(duration_seconds: float, status: str = "SUCCESS"):
    """记录 LangGraph 工作流总耗时"""
    AGENT_WORKFLOW_DURATION.observe(duration_seconds)
    AGENT_WORKFLOW_TOTAL.labels(status=status, node="workflow").inc()


def record_mq_consume(queue: str, status: str):
    """记录 MQ 消费结果"""
    MQ_CONSUME_TOTAL.labels(queue=queue, status=status).inc()


def record_quota_check(quota_type: str, result: str):
    """记录配额校验结果"""
    QUOTA_CHECK_TOTAL.labels(type=quota_type, result=result).inc()


# ========== v6 外部工具调用监控 ==========
# 用于监控 ai-outfit 工具拓展（价格平衡/库存/趋势/天气）的调用情况和熔断状态

TOOL_CALL_TOTAL = Counter(
    "ai_tool_call_total",
    "v6 外部工具调用总数",
    ["tool", "status"],  # tool: price_balance/inventory/trending_styles/weather; status: success/fallback/timeout/circuit_open/error/disabled
)

TOOL_CALL_DURATION = Histogram(
    "ai_tool_call_duration_seconds",
    "v6 外部工具调用耗时分布（秒）",
    ["tool"],
    buckets=(0.05, 0.1, 0.5, 1, 2, 5, 10, 30),
)

# 工具熔断状态：state=closed 表示正常，state=open 表示已熔断
TOOL_CIRCUIT_STATE = Gauge(
    "ai_tool_circuit_state",
    "v6 外部工具熔断状态（1=open 熔断中, 0=closed 正常）",
    ["tool"],
)


def record_tool_call(tool: str, status: str, duration_seconds: float | None = None):
    """记录一次外部工具调用结果

    Args:
        tool: 工具名（price_balance / inventory / trending_styles / weather）
        status: 调用结果状态
            - success: 调用成功
            - fallback: 调用失败，使用 fallback 降级
            - timeout: 调用超时
            - circuit_open: 熔断中，跳过调用
            - error: 调用异常
            - disabled: 工具被禁用
        duration_seconds: 调用耗时（秒），None 时不记录耗时
    """
    TOOL_CALL_TOTAL.labels(tool=tool, status=status).inc()
    if duration_seconds is not None:
        TOOL_CALL_DURATION.labels(tool=tool).observe(duration_seconds)


def set_tool_circuit_open(tool: str, is_open: bool):
    """更新工具熔断状态

    Args:
        tool: 工具名
        is_open: True 表示熔断中（open），False 表示正常（closed）
    """
    TOOL_CIRCUIT_STATE.labels(tool=tool).set(1 if is_open else 0)
