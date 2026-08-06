"""
基于 Redis 的分布式锁（对齐 Java 侧 Redisson RLock 模式）

Java 侧实现：RedissonClient.getLock(key).tryLock(waitTime, leaseTime, SECONDS)
Python 侧等价实现：SET key value NX PX leaseTime + Lua 原子释放

设计要点（参考 ZMall Java 后端 RedissonConfig + SeckillOrderListener）：
1. waitTime=0：抢不到锁立即返回，避免请求堆积（高并发场景）
2. leaseTime=30s：业务兜底防死锁，正常执行几毫秒即可完成
3. Lua 脚本释放：避免误删别人持有的锁（值校验 + 原子 del）
4. key 命名规范：lock:{业务域}:{操作}:{唯一标识}（对齐 Java 侧 lock:seckill:order:create:{orderId}）

使用方式（async with 上下文管理器）：
    async with DistributedLock(redis, "lock:outfit:feedback:task:xxx",
                                wait_timeout=0, lease_timeout=30) as acquired:
        if not acquired:
            return task_id, "正在处理上一条反馈，请稍候"
        # 临界区业务逻辑
"""
import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

# Lua 脚本：原子释放锁（值校验，避免误删别人持有的锁）
# KEYS[1] = lock key, ARGV[1] = lock value (持有者标识)
# 返回 1 表示释放成功，0 表示锁不存在或不属于当前持有者
_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""

# Lua 脚本：原子续期（看门狗等价物，可选使用）
# KEYS[1] = lock key, ARGV[1] = lock value, ARGV[2] = 新 TTL（毫秒）
_RENEW_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
else
    return 0
end
"""


class DistributedLock:
    """基于 Redis SET NX PX 的分布式锁（对齐 Java Redisson RLock 语义）

    与 Java 侧 Redisson.tryLock(waitTime, leaseTime, TimeUnit) 等价：
    - waitTime=0：非阻塞获取，抢不到立即返回（对应 Redisson tryLock() 无参版）
    - waitTime>0：轮询等待，每 50ms 重试一次直到超时
    - leaseTime>0：显式租约，不启用看门狗（对应 Redisson tryLock(0, 30, SECONDS)）
    - leaseTime=-1：启用看门狗自动续期（对应 Redisson 默认 tryLock()）

    注意：redis.asyncio 不支持 blocking BLPOP 等阻塞等待，waitTime>0 时用轮询实现。
    """

    __slots__ = ("_redis", "_key", "_value", "_wait_timeout",
                 "_lease_timeout", "_acquired", "_watchdog_task")

    def __init__(
        self,
        redis,
        key: str,
        wait_timeout: float = 0.0,
        lease_timeout: float = 30.0,
    ):
        """
        Args:
            redis: redis.asyncio.Redis 实例
            key: 锁 key（建议遵循 lock:{业务域}:{操作}:{id} 规范）
            wait_timeout: 等待获取锁的最长时间（秒），0 表示非阻塞
            lease_timeout: 锁租约时长（秒），-1 表示启用看门狗自动续期
        """
        self._redis = redis
        self._key = key
        self._value = str(uuid.uuid4())  # 持有者标识，释放时校验
        self._wait_timeout = wait_timeout
        self._lease_timeout = lease_timeout
        self._acquired = False
        self._watchdog_task: asyncio.Task | None = None

    async def acquire(self) -> bool:
        """尝试获取锁，成功返回 True，失败返回 False

        对齐 Java Redisson RLock.tryLock(waitTime, leaseTime, TimeUnit)：
        - waitTime=0 + leaseTime=30：抢不到立即返回，30s 兜底防死锁
        - waitTime>0：轮询等待
        - leaseTime=-1：启用看门狗（每 10s 续期到 30s）
        """
        lease_ms = int(self._lease_timeout * 1000) if self._lease_timeout > 0 else 30000
        # SET key value NX PX lease_ms（原子获取）
        if self._wait_timeout <= 0:
            ok = await self._redis.set(self._key, self._value, nx=True, px=lease_ms)
            if ok:
                self._acquired = True
                if self._lease_timeout == -1:
                    self._start_watchdog()
                return True
            return False
        # 轮询等待（wait_timeout > 0）
        deadline = asyncio.get_event_loop().time() + self._wait_timeout
        poll_interval = 0.05  # 50ms 轮询一次
        while True:
            ok = await self._redis.set(self._key, self._value, nx=True, px=lease_ms)
            if ok:
                self._acquired = True
                if self._lease_timeout == -1:
                    self._start_watchdog()
                return True
            if asyncio.get_event_loop().time() >= deadline:
                return False
            await asyncio.sleep(poll_interval)

    def _start_watchdog(self):
        """启动看门狗任务，每 10s 把 TTL 续到 30s（对齐 Redisson 默认行为）"""

        async def _renew_loop():
            while self._acquired:
                try:
                    await asyncio.sleep(10)
                    if not self._acquired:
                        break
                    ok = await self._redis.eval(
                        _RENEW_LUA, 1, self._key, self._value, 30000
                    )
                    if not ok:
                        # 锁已被释放或被抢占，停止续期
                        logger.warning("[DistributedLock] 续期失败（锁已失效）: key=%s", self._key)
                        break
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.warning("[DistributedLock] 续期异常: key=%s, error=%s", self._key, e)
                    break

        self._watchdog_task = asyncio.create_task(_renew_loop())

    async def release(self) -> bool:
        """释放锁（Lua 原子操作，避免误删别人持有的锁）"""
        self._acquired = False
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None
        try:
            result = await self._redis.eval(_RELEASE_LUA, 1, self._key, self._value)
            return bool(result)
        except Exception as e:
            logger.error("[DistributedLock] 释放锁异常: key=%s, error=%s", self._key, e)
            return False

    async def __aenter__(self) -> bool:
        return await self.acquire()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.release()
