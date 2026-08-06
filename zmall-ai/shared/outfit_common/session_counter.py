"""AI 随心搭·"换一套"会话计数

ai-models 商品驱动模式和 ai-outfit 风格驱动模式共用此实现。
共用同一 Redis Key `ai:outfit:session:{userId}:count`，TTL 30min。

规则：每次生成都需要扣费（不支持免费重试）。
"""
# Redis Key 前缀（两种模式共用同一计数池，体现"同一功能两种入口"的产品定位）
SESSION_COUNT_PREFIX = "ai:outfit:session:"
SESSION_COUNT_TTL = 30 * 60  # 30min

# Lua 脚本：原子 INCR 并返回旧值，每次重置 TTL 30min
# 返回 INCR 前的旧值（首次返回 0）
# 用户活跃则会话延长（每次 INCR 都重置 TTL）
_SESSION_INCR_LUA = """
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local current = redis.call('GET', key)
local old_value = 0
if current then
    old_value = tonumber(current)
end
redis.call('SET', key, old_value + 1, 'EX', ttl)
return old_value
"""


def session_key(user_id: int) -> str:
    """构造用户会话计数的 Redis Key"""
    return f"{SESSION_COUNT_PREFIX}{user_id}:count"


def should_deduct(old_count: int) -> bool:
    """判断本次是否需要扣费

    当前策略：每次生成都需要扣费，不支持免费重试。
    """
    return True


async def incr_and_get_old_count(redis, user_id: int) -> int:
    """原子 INCR 会话计数并返回旧值

    Args:
        redis: aioredis.Redis 实例
        user_id: 用户 ID
    Returns:
        INCR 前的旧值（首次返回 0）
    """
    key = session_key(user_id)
    old_count = await redis.eval(_SESSION_INCR_LUA, 1, key, SESSION_COUNT_TTL)
    return int(old_count) if old_count is not None else 0


async def decr_session_count(redis, user_id: int) -> None:
    """回滚会话计数（配额预扣失败时调用，避免计数白白增加）

    Args:
        redis: aioredis.Redis 实例
        user_id: 用户 ID
    """
    key = session_key(user_id)
    await redis.decr(key)
