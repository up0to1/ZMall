"""
天气/季节服务（uapis.cn API）

用途：查询用户所在地实时天气，推导季节，给搭配推荐提供季节约束
接入环节：节点1 intent_understanding（注入季节）+ 节点2 qdrant_search（季节过滤）
         + 节点3 outfit_combination（format_weather_hint_for_llm 提供给 LLM 软提示）

降级策略：
1. API Key 未配置 → 按月份推断季节
2. API 调用失败 → 按月份推断季节
3. 城市未知 → 用默认城市（settings.weather_default_city）

设计原则：
1. 失败时永远返回有效结果（不抛异常），主流程不阻塞
2. 季节推导基于温度（仅用作 Qdrant 候选池硬过滤的粗筛标签）：
   - <10°C: winter
   - 10-20°C: autumn
   - 20-27°C: spring
   - ≥27°C: summer
3. 返回的 dict 结构稳定，调用方可直接 .get() 取字段
4. 调用 uapis 的 extended=true&indices=true 拿扩展字段
   （体感温度/湿度/风力/空气质量/官方穿衣指数），让 LLM 基于温度而非季节决策穿衣
"""
import datetime
import json
import logging

import httpx

logger = logging.getLogger(__name__)


# 月份 → 季节映射（北半球，作为天气 API 不可用时的降级）
_MONTH_TO_SEASON: dict[int, str] = {}
for m in (3, 4, 5):
    _MONTH_TO_SEASON[m] = "spring"
for m in (6, 7, 8):
    _MONTH_TO_SEASON[m] = "summer"
for m in (9, 10, 11):
    _MONTH_TO_SEASON[m] = "autumn"
for m in (12, 1, 2):
    _MONTH_TO_SEASON[m] = "winter"


# 季节 → 风格建议关键词
_SEASON_STYLE_SUGGESTION: dict[str, str] = {
    "winter": "厚外套/毛衣/羽绒服/大衣/保暖",
    "autumn": "薄外套/针织衫/风衣/层次感",
    "spring": "衬衫/薄毛衣/休闲外套/轻薄",
    "summer": "短袖/短裤/连衣裙/透气/轻薄面料",
}


# 天气结果 Redis 缓存（天气变化频率低，TTL 1800s）
_WEATHER_CACHE_TTL = 1800
_WEATHER_CACHE_PREFIX = "ai:weather:"

# uapis.cn 天气 API 完整地址
_UAPIS_WEATHER_URL = "https://uapis.cn/api/v1/misc/weather"


async def get_weather(
    city: str = "",
    api_key: str = "",
    api_url: str = _UAPIS_WEATHER_URL,
    redis=None,  # 可选 Redis 客户端，启用缓存；None 时降级直查
) -> dict:
    """查询城市天气（uapis.cn API）

    Args:
        city: 城市名（如 "北京"），支持中文和英文（如 "Tokyo"），空时用默认城市"北京"兜底
        api_key: uapis.cn API Key（以 uapi- 开头），空时走月份降级
        api_url: uapis.cn 天气 API 完整地址
        redis: 可选 Redis 客户端（aioredis），启用缓存；None 时降级直查

    Returns:
        {
            "city": "北京",
            "temp": 5,                  # 气温（℃），无数据时为 None
            "season": "winter",         # 推导出的季节（仅用于 Qdrant 硬过滤粗筛）
            "weather_desc": "晴",       # 天气描述
            "suggestion": "厚外套/毛衣/羽绒服/大衣/保暖",  # 季节风格建议（粗粒度）
            "source": "uapis_api" / "month_fallback",
            # P0 增强字段（extended=true 返回，可能为 None）
            "feels_like": 2,            # 体感温度（℃）— LLM 决策穿衣厚度的关键依据
            "humidity": 20,             # 相对湿度（%）
            "wind_power": "微风",       # 风力等级
            "aqi": 56,                  # 空气质量指数
            "aqi_category": "良",       # 空气质量等级描述
            "uv": 2.9,                  # 紫外线指数
            # P0 增强字段（indices=true 返回，可能为 None）
            "clothing_index": {         # 官方穿衣指数（比季节更精准）
                "level": "较舒适",
                "brief": "微凉",
                "advice": "建议穿薄外套、卫衣或长袖衬衫",
            },
        }
    """
    if not api_key:
        logger.info("[天气工具] 未配置 API Key，按月份推断季节")
        return _fallback_by_month(city)

    if not city:
        city = "北京"  # 默认城市

    # 查 Redis 缓存（命中直接返回，未命中回源）
    cache_key = f"{_WEATHER_CACHE_PREFIX}{city}"
    if redis is not None:
        try:
            cached = await redis.get(cache_key)
            if cached is not None:
                try:
                    result = json.loads(cached)
                    logger.info("[天气工具] Redis 缓存命中: city=%s, temp=%s, season=%s",
                                city, result.get("temp"), result.get("season"))
                    return result
                except (TypeError, ValueError) as e:
                    logger.warning("[天气工具] Redis 缓存反序列化失败，回源: %s", e)
        except Exception as e:
            logger.warning("[天气工具] Redis 缓存读取失败（降级直查）: %s", e)

    try:
        async with httpx.AsyncClient(trust_env=False, timeout=5.0) as client:
            # uapis.cn 直接支持城市名查询，无需先查 GeoAPI
            # P0 增强：extended=true 拿体感温度/湿度/风力/AQI/UV；indices=true 拿官方穿衣指数
            resp = await client.get(
                api_url,
                params={
                    "city": city,
                    "lang": "zh",
                    "extended": "true",
                    "indices": "true",
                },
                headers={"Authorization": f"Bearer {api_key}"},
            )

            # 非 2xx 响应处理
            if resp.status_code == 400:
                data = resp.json()
                logger.warning("[天气工具] uapis 参数无效: %s", data.get("message", ""))
                return _fallback_by_month(city)
            elif resp.status_code == 404:
                data = resp.json()
                logger.warning("[天气工具] uapis 城市未找到: %s, city=%s", data.get("message", ""), city)
                return _fallback_by_month(city)
            elif resp.status_code == 429:
                logger.warning("[天气工具] uapis 请求被限流，降级月份推断: city=%s", city)
                return _fallback_by_month(city)
            elif resp.status_code == 503:
                logger.warning("[天气工具] uapis 天气服务暂时不可用，降级月份推断")
                return _fallback_by_month(city)
            elif resp.status_code == 500:
                logger.warning("[天气工具] uapis 服务器内部错误，降级月份推断")
                return _fallback_by_month(city)
            elif resp.status_code != 200:
                logger.warning("[天气工具] uapis API 状态码异常: %s", resp.status_code)
                return _fallback_by_month(city)

            data = resp.json()
            # uapis.cn 返回结构：{"city": "北京", "weather": "晴", "temperature": 18.3, ...}
            # temperature 缺失时返回 None 走月份降级
            raw_temp = data.get("temperature")
            try:
                if raw_temp is None or raw_temp == "":
                    logger.warning("[天气工具] uapis 缺失 temperature 字段，降级月份推断")
                    return _fallback_by_month(city)
                temp = int(float(raw_temp))
            except (TypeError, ValueError):
                logger.warning("[天气工具] temperature 字段转换失败: %r，降级月份推断", raw_temp)
                return _fallback_by_month(city)

            weather_desc = data.get("weather", "未知")
            # uapis.cn 返回的 city 字段优先，否则用传入的 city
            result_city = data.get("city") or city
            season = _temp_to_season(temp)

            # P0 增强：解析扩展字段（extended=true 返回，可能缺失或为 None）
            # 体感温度优先用于 LLM 决策穿衣厚度（比气温更贴近真实感受）
            raw_feels_like = data.get("feels_like")
            feels_like = None
            try:
                if raw_feels_like is not None and raw_feels_like != "":
                    feels_like = int(float(raw_feels_like))
            except (TypeError, ValueError):
                pass

            # 湿度（%）
            raw_humidity = data.get("humidity")
            humidity = None
            try:
                if raw_humidity is not None and raw_humidity != "":
                    humidity = int(raw_humidity)
            except (TypeError, ValueError):
                pass

            # 风力等级（文本，如"微风"/"3级"）
            wind_power = data.get("wind_power") or data.get("wind_scale")

            # 空气质量（AQI 数值 + 等级描述）
            aqi = data.get("aqi")
            aqi_category = data.get("aqi_category")

            # 紫外线指数
            uv = data.get("uv")

            # P0 增强：解析官方穿衣指数（indices=true 返回的 life_indices.clothing）
            # 比 _SEASON_STYLE_SUGGESTION 的季节级建议更精准（基于气象模型推导）
            clothing_index = None
            life_indices = data.get("life_indices")
            if isinstance(life_indices, dict):
                raw_clothing = life_indices.get("clothing")
                if isinstance(raw_clothing, dict):
                    clothing_index = {
                        "level": raw_clothing.get("level", ""),
                        "brief": raw_clothing.get("brief", ""),
                        "advice": raw_clothing.get("advice", ""),
                    }

            weather_result = {
                "city": result_city,
                "temp": temp,
                "season": season,
                "weather_desc": weather_desc,
                "suggestion": _SEASON_STYLE_SUGGESTION.get(season, ""),
                "source": "uapis_api",
                # 向后兼容：旧缓存无这些字段时 .get() 返回 None
                "feels_like": feels_like,
                "humidity": humidity,
                "wind_power": wind_power,
                "aqi": aqi,
                "aqi_category": aqi_category,
                "uv": uv,
                "clothing_index": clothing_index,
            }

            # 回填 Redis 缓存（仅缓存 API 成功结果，不缓存 fallback）
            if redis is not None:
                try:
                    await redis.set(
                        cache_key,
                        json.dumps(weather_result),
                        ex=_WEATHER_CACHE_TTL,
                    )
                    logger.info("[天气工具] Redis 缓存已写入: key=%s, TTL=%ss", cache_key, _WEATHER_CACHE_TTL)
                except Exception as e:
                    logger.warning("[天气工具] Redis 缓存回填失败（不影响主流程）: %s", e)

            return weather_result
    except httpx.TimeoutException:
        logger.warning("[天气工具] uapis API 请求超时，降级月份推断: city=%s", city)
        return _fallback_by_month(city)
    except httpx.ConnectError as e:
        logger.warning("[天气工具] uapis API 网络连接失败，降级月份推断: %s", e)
        return _fallback_by_month(city)
    except Exception as e:
        logger.warning("[天气工具] uapis API 调用异常: %s，降级月份推断", e)
        return _fallback_by_month(city)


def _temp_to_season(temp: int) -> str:
    """根据温度推导季节

    阈值（适合中国大部分地区）：
    - <10°C: winter
    - 10-20°C: autumn
    - 20-27°C: spring
    - ≥27°C: summer
    """
    if temp < 10:
        return "winter"
    elif temp < 20:
        return "autumn"
    elif temp < 27:
        return "spring"
    else:
        return "summer"


def _fallback_by_month(city: str = "") -> dict:
    """按月份推断季节（API 不可用时降级）"""
    month = datetime.datetime.now().month
    season = _MONTH_TO_SEASON.get(month, "summer")
    return {
        "city": city or "unknown",
        "temp": None,
        "season": season,
        "weather_desc": "unknown",
        "suggestion": _SEASON_STYLE_SUGGESTION.get(season, ""),
        "source": "month_fallback",
    }


def format_weather_hint_for_llm(weather: dict) -> str:
    """把天气结果格式化为 LLM 可读的提示文本

    - 季节标签（spring/summer/autumn/winter）仅用于 Qdrant 候选池硬过滤粗筛，
      LLM 决策时应以温度（尤其是体感温度）为准，而非季节标签
    - 同一温度在不同地区体感不同（18°C 在中国是春天，英国算夏天），
      季节标签无法反映这种差异，温度本身才是穿衣决策的硬依据
    - 15~20°C 是「又冷又热」的过渡气温：短袖+薄外套叠穿、长袖+薄外套均可，
      方便用户根据室内外/昼夜温差增减，不应强制只推长袖或只推短袖
    """
    if not weather:
        return ""
    season = weather.get("season", "")
    if not season:
        return ""
    temp = weather.get("temp")
    city = weather.get("city", "")
    suggestion = weather.get("suggestion", "")
    weather_desc = weather.get("weather_desc", "")

    # 可能 None，向后兼容旧缓存
    feels_like = weather.get("feels_like")
    humidity = weather.get("humidity")
    wind_power = weather.get("wind_power")
    aqi = weather.get("aqi")
    aqi_category = weather.get("aqi_category")
    uv = weather.get("uv")
    clothing_index = weather.get("clothing_index")

    temp_str = f"{temp}°C" if temp is not None else "未知温度"
    feels_like_str = f"{feels_like}°C" if feels_like is not None else "未知"

    # 构建扩展气象字段块（仅展示有的字段）
    ext_lines = []
    if feels_like is not None:
        ext_lines.append(f"- 体感温度: {feels_like}°C")
    if humidity is not None:
        ext_lines.append(f"- 湿度: {humidity}%")
    if wind_power:
        ext_lines.append(f"- 风力: {wind_power}")
    if aqi is not None and aqi_category:
        ext_lines.append(f"- 空气质量: {aqi_category}（AQI {aqi}）")
    if uv is not None:
        ext_lines.append(f"- 紫外线指数: {uv}")
    ext_block = "\n".join(ext_lines)

    # 构建官方穿衣指数块（比季节级 suggestion 更精准）
    clothing_block = ""
    if clothing_index and (clothing_index.get("advice") or clothing_index.get("level")):
        clothing_block = (
            f"\n- 官方穿衣指数: {clothing_index.get('level', '')}"
            f"（{clothing_index.get('brief', '')}）"
            f"— {clothing_index.get('advice', '')}"
        )

    return (
        f"【实时天气】\n"
        f"- 城市: {city or '未知'}\n"
        f"- 天气: {weather_desc}, 气温 {temp_str}\n"
        f"{ext_block}\n"
        f"- 推导季节: {season}（仅用于候选池粗筛，决策穿衣以温度为准）\n"
        f"- 季节风格建议（粗粒度）: {suggestion}"
        f"{clothing_block}\n\n"
        f"【穿衣决策原则】\n"
        f"1. 以温度（尤其是体感温度 {feels_like_str}）为准决定穿衣厚度，季节标签仅作参考\n"
        f"2. 15~20°C 是「又冷又热」的过渡气温：可短袖+薄外套叠穿，或长袖+薄外套，"
        f"方便用户根据室内外/昼夜温差增减，不应强制只推长袖或只推短袖\n"
        f"3. 湿冷（湿度高+温度低）体感比实际温度更冷，需加厚保暖层；干冷可适当轻薄\n"
        f"4. 雨雪天气需考虑防水外套；晴天可适当轻薄\n"
        f"5. 优先参考官方穿衣指数的层级建议（基于气象模型推导，比季节更精准）\n"
        f"6. 避免推荐反季商品（如夏季推羽绒服、冬季推短袖）"
    )
