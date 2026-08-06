"""
意图理解子 Agent 的 ReAct Tool 执行器（场景 2）

LlmClient.react_intent 调用本模块的 IntentToolExecutor 执行 LLM 自主选择的 Tool：
  - parse_note: 解析自然语言备注（如"下周面试，想要正式一点"）
  - rewrite_query_hyde: HyDE 查询改写（场景化检索文本）
  - analyze_user_photo: 用户真人照片视觉特征分析
  - get_weather_season: 查询天气推导季节
  - encode_query_vector: 文本向量编码

设计要点（与 agent_tools.ToolExecutor 保持一致）：
- IntentToolExecutor 持有 user_id / photo_session_key 等上下文
- 所有 Tool 执行失败返回 {"error": ...}，不抛异常（避免中断 ReAct 循环）
- LLM 根据用户输入语义自主决定调用哪些工具、顺序如何、是否调用
  例：用户输入"商务"时跳过 weather；用户输入"夏日海边"时调用 weather 验证季节
"""
import logging

from app.api.deps import get_embed_client, get_llm_client, get_redis

logger = logging.getLogger(__name__)


class IntentToolExecutor:
    """意图理解子 Agent 的 ReAct Tool 执行器

    每次意图理解子 Agent 运行创建一个实例，持有 user_id / photo_session_key 等上下文。
    LLM 通过 react_intent 调用 executor.execute(tool_name, action_input)。
    """

    def __init__(
        self,
        user_id: int | None = None,
        photo_session_key: str | None = None,
    ):
        self.user_id = user_id
        # photo_session_key 作为"用户已上传照片"的标志位（非 None 表示有照片会话）
        # 实际 Redis Key 固定为 ai:photo:session:{user_id}，不直接使用此参数值
        self.photo_session_key = photo_session_key
        # 缓存用户照片 bytes，避免 LLM 多次调用 analyze_user_photo 时重复加载
        self._cached_photo: bytes | None = None
        self._photo_loaded = False

    async def execute(self, tool_name: str, action_input: dict) -> dict:
        """执行 Tool

        Args:
            tool_name: parse_note / rewrite_query_hyde / analyze_user_photo /
                       get_weather_season / encode_query_vector
            action_input: Tool 参数 dict
        Returns:
            Tool 执行结果 dict；失败时返回 {"error": "..."}
        """
        try:
            if tool_name == "parse_note":
                return await self._parse_note(action_input)
            if tool_name == "rewrite_query_hyde":
                return await self._rewrite_query_hyde(action_input)
            if tool_name == "analyze_user_photo":
                return await self._analyze_user_photo(action_input)
            if tool_name == "get_weather_season":
                return await self._get_weather_season(action_input)
            if tool_name == "encode_query_vector":
                return await self._encode_query_vector(action_input)
            return {"error": f"未知 Tool: {tool_name}"}
        except Exception as e:
            logger.warning("[IntentAgent] Tool %s 执行异常: %s", tool_name, e)
            return {"error": f"Tool {tool_name} 执行失败: {e}"}

    # ------------------------------------------------------------------
    # Tool 1: parse_note - 解析自然语言备注
    # ------------------------------------------------------------------
    async def _parse_note(self, action_input: dict) -> dict:
        """解析用户备注（如"下周面试，想要正式一点，最好黑色"）

        LLM 在用户填写了 note 字段时调用，提取结构化偏好。
        """
        note = action_input.get("note")
        if not note or not isinstance(note, str) or not note.strip():
            return {"error": "note 为空或非字符串"}

        llm_client = await get_llm_client()
        result = await llm_client.parse_note(note.strip())
        if not result:
            return {"error": "parse_note 返回空"}
        logger.info("[IntentAgent] parse_note: note=%s → %s", note[:50], result)
        return {"parsed": result}

    # ------------------------------------------------------------------
    # Tool 2: rewrite_query_hyde - HyDE 查询改写
    # ------------------------------------------------------------------
    async def _rewrite_query_hyde(self, action_input: dict) -> dict:
        """HyDE 查询改写（场景化检索文本）

        LLM 在用户场景描述明确（如"下周面试""夏日海边"）时调用，提升检索准确度。
        """
        style_tags = list(action_input.get("style_tags") or [])
        scene_desc = action_input.get("scene_desc")
        color = action_input.get("color")

        if not style_tags and not scene_desc and not color:
            return {"error": "style_tags/scene_desc/color 至少填一项"}

        llm_client = await get_llm_client()
        hyde_text = await llm_client.rewrite_query_hyde(style_tags, scene_desc, color)
        if not hyde_text:
            return {"error": "HyDE 改写返回空，可使用原 query_text"}
        logger.info("[IntentAgent] rewrite_query_hyde: style=%s, scene=%s → %s",
                     style_tags, scene_desc, hyde_text)
        return {"hyde_text": hyde_text}

    # ------------------------------------------------------------------
    # Tool 3: analyze_user_photo - 用户照片视觉特征分析
    # ------------------------------------------------------------------
    async def _analyze_user_photo(self, action_input: dict) -> dict:
        """分析用户真人照片（性别/肤色/身材/年龄/风格倾向）

        LLM 在用户上传了真人照片时调用，提取视觉特征用于搭配推荐。
        """
        photo_bytes = await self._load_user_photo()
        if not photo_bytes:
            return {"error": "未上传照片或照片加载失败"}

        llm_client = await get_llm_client()
        profile = await llm_client.analyze_user_photo(photo_bytes)
        if not profile:
            return {"error": "analyze_user_photo 返回空"}
        logger.info("[IntentAgent] analyze_user_photo: userId=%s → %s",
                     self.user_id, profile)
        return {"user_visual_profile": profile}

    # ------------------------------------------------------------------
    # Tool 4: get_weather_season - 查询天气推导季节
    # ------------------------------------------------------------------
    async def _get_weather_season(self, action_input: dict) -> dict:
        """查询天气推导季节（如"北京 5°C → winter"）

        LLM 在用户输入含季节线索（如"夏日""冬天"）时调用，验证季节。
        """
        # 延迟导入避免循环依赖
        from app.core.config import settings
        from shared.external_services.weather_service import get_weather

        if not settings.weather_tool_enabled:
            return {"error": "weather_tool_enabled=False，天气工具未开启"}

        city = action_input.get("city") or settings.weather_default_city
        api_key = settings.weather_api_key
        api_url = settings.weather_api_url

        if not api_key:
            return {"error": "weather_api_key 未配置"}

        redis_client = await get_redis()
        weather_info = await get_weather(city, api_key, api_url, redis=redis_client)
        if not weather_info:
            return {"error": "get_weather 返回空"}
        logger.info("[IntentAgent] get_weather_season: city=%s → season=%s",
                     city, weather_info.get("season"))
        return {
            "weather_info": weather_info,
            "season": weather_info.get("season"),
        }

    # ------------------------------------------------------------------
    # Tool 5: encode_query_vector - 文本向量编码
    # ------------------------------------------------------------------
    async def _encode_query_vector(self, action_input: dict) -> dict:
        """文本向量编码（CLIP 1024 维）

        LLM 在确定最终 query_text 后调用，生成向量供节点2 检索使用。
        必须调用：无论 LLM 是否调用了其他工具，最终都需要生成 query_vector。
        """
        query_text = action_input.get("query_text")
        if not query_text or not isinstance(query_text, str) or not query_text.strip():
            return {"error": "query_text 为空或非字符串"}

        embed_client = await get_embed_client()
        vector = await embed_client.encode_text(query_text.strip())
        if not vector:
            return {"error": "encode_text 返回空"}
        logger.info("[IntentAgent] encode_query_vector: query=%s → dim=%d",
                     query_text[:50], len(vector))
        return {"query_vector": vector}

    # ------------------------------------------------------------------
    # 辅助方法：加载用户照片（带缓存）
    # ------------------------------------------------------------------
    async def _load_user_photo(self) -> bytes | None:
        """从 Redis 加载用户照片 bytes，结果缓存到实例

        LLM 可能多次调用 analyze_user_photo，避免重复加载。
        """
        if self._photo_loaded:
            return self._cached_photo

        self._photo_loaded = True
        if not self.photo_session_key or self.user_id is None:
            return None

        try:
            import base64
            redis = await get_redis()
            # 用 photo_session_key（= "{userId}:{sessionId}"）构造 Redis Key
            photo_b64 = await redis.get(f"ai:photo:session:{self.photo_session_key}")
            if not photo_b64:
                return None
            self._cached_photo = base64.b64decode(photo_b64)
            return self._cached_photo
        except Exception as e:
            logger.warning("[IntentAgent] 加载用户照片失败: %s", e)
            return None
