"""
多 Agent 决策 LLM 工具函数（ai-models 增强版）

增强点（v3）：
1. _call_llm / _call_vision_llm 加重试 + 指数退避（参考 VtonClient.try_on_with_retry）
2. 返回值改为 LLMResult dataclass，带 is_fallback 标记，区分"真实评分"和"LLM 调用失败"
3. Agent 级 Prometheus 埋点（调用次数 / 耗时 / fallback 率 / 重试次数）
4. httpx.AsyncClient 单例化，复用 TLS 连接池
5. 温度参数可配置（策划阶段 0.3 / 评估阶段 0.0）

与 ai-outfit 的 LlmClient 解耦：
- 不引入 HyDE / note / feedback / reflect / ReAct 等随心搭专用方法
- 配置从 settings 读取，无单例类

设计文档 §1.8.5：5 角色 Agent 都通过这两个函数调用 LLM。
"""
import asyncio
import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# LLM 调用超时
LLM_PLAN_TIMEOUT = 15   # 策划阶段纯文本，15s 足够
LLM_REVIEW_TIMEOUT = 30  # 评估阶段含图像理解（VL 模型），需更长超时

# 重试参数（参考 VtonClient.try_on_with_retry）
MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]  # 秒，指数退避

# 模块级 httpx.AsyncClient 单例（复用 TLS 连接池）
_text_client: httpx.AsyncClient | None = None
_vision_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def _get_text_client() -> httpx.AsyncClient:
    """获取纯文本 LLM 调用的单例 httpx client"""
    global _text_client
    if _text_client is None or _text_client.is_closed:
        async with _client_lock:
            if _text_client is None or _text_client.is_closed:
                _text_client = httpx.AsyncClient(timeout=LLM_PLAN_TIMEOUT)
    return _text_client


async def _get_vision_client() -> httpx.AsyncClient:
    """获取视觉 LLM 调用的单例 httpx client"""
    global _vision_client
    if _vision_client is None or _vision_client.is_closed:
        async with _client_lock:
            if _vision_client is None or _vision_client.is_closed:
                _vision_client = httpx.AsyncClient(timeout=LLM_REVIEW_TIMEOUT)
    return _vision_client


async def close_llm_clients():
    """关闭 LLM httpx 客户端（应用退出时调用）"""
    global _text_client, _vision_client
    for client in (_text_client, _vision_client):
        if client and not client.is_closed:
            try:
                await client.aclose()
            except Exception as e:
                logger.warning("关闭 LLM httpx client 异常: %s", e)
    _text_client = None
    _vision_client = None


@dataclass
class LLMResult:
    """LLM 调用结果（带 fallback 标记）

    is_fallback=True 表示 LLM 调用失败，data 为降级值；
    is_fallback=False 表示 LLM 调用成功，data 为真实输出。
    """
    data: dict | None
    is_fallback: bool = False
    error: str | None = None
    retries: int = 0
    elapsed_ms: float = 0.0


def _resolve_api_url() -> str:
    """获取完整的 OpenAI 兼容 endpoint

    settings.llm_api_url 配置为 base URL（如 https://dashscope.aliyuncs.com/compatible-mode/v1），
    自动补全 /chat/completions 后缀。
    """
    base = (settings.llm_api_url or "").rstrip("/")
    if not base:
        return ""
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _metrics_record(
    agent_name: str, elapsed_ms: float, retries: int, is_fallback: bool,
) -> None:
    """Agent 级 Prometheus 埋点（best-effort，失败不影响主流程）

    埋点维度：
    - ai_model_agent_llm_calls_total{agent, status}
    - ai_model_agent_llm_duration_seconds{agent}
    - ai_model_agent_llm_retries_total{agent}
    """
    try:
        from shared.metrics import _AGENT_LLM_CALLS, _AGENT_LLM_DURATION, _AGENT_LLM_RETRIES
        status = "fallback" if is_fallback else "success"
        _AGENT_LLM_CALLS.labels(agent=agent_name, status=status).inc()
        _AGENT_LLM_DURATION.labels(agent=agent_name).observe(elapsed_ms / 1000.0)
        if retries > 0:
            _AGENT_LLM_RETRIES.labels(agent=agent_name).inc(retries)
    except Exception:
        pass  # 埋点失败不影响主流程


async def _call_llm_with_retry(
    model: str,
    system_prompt: str,
    user_prompt: str,
    agent_name: str = "unknown",
    timeout: int = LLM_PLAN_TIMEOUT,
    temperature: float = 0.3,
    max_retries: int = MAX_RETRIES,
) -> LLMResult:
    """通用纯文本 LLM 调用（带重试 + fallback 标记 + 埋点）

    Args:
        model: 模型名（如 qwen-flash）
        system_prompt: system message
        user_prompt: user message 文本
        agent_name: Agent 名称（用于埋点，如 "stylist_eu_plan"）
        timeout: HTTP 超时秒数
        temperature: 温度参数（策划阶段建议 0.3，评估阶段建议 0.0）
        max_retries: 最大重试次数
    Returns:
        LLMResult：含 data / is_fallback / error / retries / elapsed_ms
    """
    start = time.monotonic()
    api_url = _resolve_api_url()
    api_key = settings.llm_api_key
    if not api_url or not api_key or not model:
        logger.warning("LLM 未配置（api_url/api_key/model 缺失），跳过调用: agent=%s", agent_name)
        elapsed = (time.monotonic() - start) * 1000
        _metrics_record(agent_name, elapsed, 0, True)
        return LLMResult(data=None, is_fallback=True, error="llm_not_configured", elapsed_ms=elapsed)

    client = await _get_text_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = await client.post(api_url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                elapsed = (time.monotonic() - start) * 1000
                _metrics_record(agent_name, elapsed, attempt, False)
                if attempt > 0:
                    logger.info("[LLM] %s 第 %d 次重试成功: elapsed=%.0fms", agent_name, attempt, elapsed)
                return LLMResult(data=parsed, is_fallback=False, retries=attempt, elapsed_ms=elapsed)
            # 4xx 不重试（参数错误、配额不足等）
            if 400 <= resp.status_code < 500:
                logger.error("[LLM] %s 4xx 不重试: status=%s, body=%s",
                             agent_name, resp.status_code, resp.text[:200])
                elapsed = (time.monotonic() - start) * 1000
                _metrics_record(agent_name, elapsed, attempt, True)
                return LLMResult(
                    data=None, is_fallback=True,
                    error=f"http_{resp.status_code}", retries=attempt, elapsed_ms=elapsed,
                )
            # 5xx 重试
            logger.warning("[LLM] %s 5xx 重试 (attempt=%d): status=%s",
                           agent_name, attempt, resp.status_code)
            last_exc = RuntimeError(f"http_{resp.status_code}")
        except Exception as e:
            last_exc = e
            logger.warning("[LLM] %s 异常 (attempt=%d): %s", agent_name, attempt, e)

        if attempt < max_retries - 1:
            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
            await asyncio.sleep(wait)

    elapsed = (time.monotonic() - start) * 1000
    _metrics_record(agent_name, elapsed, max_retries - 1, True)
    logger.error("[LLM] %s 重试 %d 次仍失败: last_error=%s, elapsed=%.0fms",
                 agent_name, max_retries, last_exc, elapsed)
    return LLMResult(
        data=None, is_fallback=True,
        error=str(last_exc) if last_exc else "unknown",
        retries=max_retries - 1, elapsed_ms=elapsed,
    )


async def _call_vision_llm_with_retry(
    model: str,
    system_prompt: str,
    text_prompt: str,
    image_b64: str,
    agent_name: str = "unknown",
    timeout: int = LLM_REVIEW_TIMEOUT,
    temperature: float = 0.0,
    max_retries: int = MAX_RETRIES,
) -> LLMResult:
    """图像理解 LLM 调用（带重试 + fallback 标记 + 埋点）

    Args:
        model: 视觉模型名（如 qwen3.5-flash）
        text_prompt: 文本指令（不含图像）
        image_b64: 图像 base64 编码字符串（不含 data:image/... 前缀）
        agent_name: Agent 名称（用于埋点，如 "lighting_review"）
        timeout: HTTP 超时秒数
        temperature: 温度参数（评估阶段建议 0.0，确保打分稳定）
        max_retries: 最大重试次数
    Returns:
        LLMResult：含 data / is_fallback / error / retries / elapsed_ms
    """
    start = time.monotonic()
    api_url = _resolve_api_url()
    api_key = settings.llm_api_key
    if not api_url or not api_key or not model:
        logger.warning("LLM 未配置（api_url/api_key/model 缺失），跳过 Vision 调用: agent=%s", agent_name)
        elapsed = (time.monotonic() - start) * 1000
        _metrics_record(agent_name, elapsed, 0, True)
        return LLMResult(data=None, is_fallback=True, error="llm_not_configured", elapsed_ms=elapsed)

    client = await _get_vision_client()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": text_prompt},
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{image_b64}"
            }}
        ]}
    ]
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = await client.post(api_url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                elapsed = (time.monotonic() - start) * 1000
                _metrics_record(agent_name, elapsed, attempt, False)
                if attempt > 0:
                    logger.info("[Vision] %s 第 %d 次重试成功: elapsed=%.0fms", agent_name, attempt, elapsed)
                return LLMResult(data=parsed, is_fallback=False, retries=attempt, elapsed_ms=elapsed)
            if 400 <= resp.status_code < 500:
                logger.error("[Vision] %s 4xx 不重试: status=%s, body=%s",
                             agent_name, resp.status_code, resp.text[:200])
                elapsed = (time.monotonic() - start) * 1000
                _metrics_record(agent_name, elapsed, attempt, True)
                return LLMResult(
                    data=None, is_fallback=True,
                    error=f"http_{resp.status_code}", retries=attempt, elapsed_ms=elapsed,
                )
            logger.warning("[Vision] %s 5xx 重试 (attempt=%d): status=%s",
                           agent_name, attempt, resp.status_code)
            last_exc = RuntimeError(f"http_{resp.status_code}")
        except Exception as e:
            last_exc = e
            logger.warning("[Vision] %s 异常 (attempt=%d): %s", agent_name, attempt, e)

        if attempt < max_retries - 1:
            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
            await asyncio.sleep(wait)

    elapsed = (time.monotonic() - start) * 1000
    _metrics_record(agent_name, elapsed, max_retries - 1, True)
    logger.error("[Vision] %s 重试 %d 次仍失败: last_error=%s, elapsed=%.0fms",
                 agent_name, max_retries, last_exc, elapsed)
    return LLMResult(
        data=None, is_fallback=True,
        error=str(last_exc) if last_exc else "unknown",
        retries=max_retries - 1, elapsed_ms=elapsed,
    )


# ===== 向后兼容包装（保留旧接口，内部走新的带重试版本）=====

async def _call_llm(
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int = LLM_PLAN_TIMEOUT,
) -> dict | None:
    """向后兼容包装：返回 dict 或 None（旧接口）

    新代码应直接使用 _call_llm_with_retry 获取 LLMResult（含 is_fallback 标记）。
    """
    result = await _call_llm_with_retry(
        model=model, system_prompt=system_prompt, user_prompt=user_prompt,
        agent_name="legacy", timeout=timeout,
    )
    return result.data


async def _call_vision_llm(
    model: str,
    system_prompt: str,
    text_prompt: str,
    image_b64: str,
    timeout: int = LLM_REVIEW_TIMEOUT,
) -> dict | None:
    """向后兼容包装：返回 dict 或 None（旧接口）"""
    result = await _call_vision_llm_with_retry(
        model=model, system_prompt=system_prompt, text_prompt=text_prompt,
        image_b64=image_b64, agent_name="legacy", timeout=timeout,
    )
    return result.data


def encode_image_b64(image_bytes: bytes) -> str:
    """工具函数：图片字节转 base64 字符串"""
    return base64.b64encode(image_bytes).decode("ascii")


# ===== LLM 结果缓存（按 hash(items+model_info) 缓存策划阶段输出，TTL 1h）=====

class LLMResultCache:
    """LLM 调用结果缓存

    缓存键：hash(agent_name + sorted(item_ids) + model_info_hash + prompt_hash)
    缓存值：LLMResult.data
    TTL：1 小时（策划阶段输出短期稳定，重试时可秒级返回）

    使用场景：
    - 策划阶段 EU/Asia stylist 输出（风格特征、VTON 顺序决策）
    - 商家调整参数重试时，相同商品+模特图的策划结果秒级返回

    不缓存：
    - 评估阶段 Vision LLM 输出（每次 VTON 结果图不同）
    - 后处理 actions（依赖评估结果，动态变化）
    """

    def __init__(self, ttl_seconds: int = 3600):
        self._cache: dict[str, tuple[float, dict | None]] = {}
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    @staticmethod
    def _build_key(
        agent_name: str,
        items: list[dict],
        model_info: dict | None,
        extra: str = "",
    ) -> str:
        """构造缓存键

        Args:
            agent_name: Agent 名称（如 "stylist_eu_plan"）
            items: 商品列表
            model_info: 模特图信息
            extra: 额外区分字段（如 vton_order 候选编号）
        """
        # 只取稳定的 itemId + category，避免 name/price 等可变字段影响缓存命中率
        items_sig = sorted([
            (it.get("itemId"), it.get("category"))
            for it in items
        ])
        model_sig = ""
        if model_info:
            model_sig = json.dumps(model_info, sort_keys=True, ensure_ascii=False)
        sig = f"{agent_name}|{items_sig}|{model_sig}|{extra}"
        return hashlib.sha256(sig.encode("utf-8")).hexdigest()

    async def get(
        self,
        agent_name: str,
        items: list[dict],
        model_info: dict | None = None,
        extra: str = "",
    ) -> dict | None:
        """查询缓存，未命中或过期返回 None"""
        key = self._build_key(agent_name, items, model_info, extra)
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            ts, data = entry
            if time.time() - ts > self._ttl:
                del self._cache[key]
                return None
            return data

    async def set(
        self,
        agent_name: str,
        items: list[dict],
        model_info: dict | None,
        data: dict | None,
        extra: str = "",
    ) -> None:
        """写入缓存"""
        key = self._build_key(agent_name, items, model_info, extra)
        async with self._lock:
            self._cache[key] = (time.time(), data)

    async def clear(self) -> None:
        """清空缓存"""
        async with self._lock:
            self._cache.clear()


# 模块级单例
llm_cache = LLMResultCache(ttl_seconds=3600)
