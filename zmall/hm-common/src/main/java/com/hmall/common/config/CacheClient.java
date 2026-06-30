package com.hmall.common.config;

import cn.hutool.core.util.StrUtil;
import cn.hutool.json.JSONUtil;
import lombok.RequiredArgsConstructor;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;

import static com.hmall.common.config.RedisConstants.CACHE_NULL_TTL;

@Component
@RequiredArgsConstructor
@ConditionalOnClass(name = {"org.springframework.data.redis.core.StringRedisTemplate",
        "org.redisson.api.RedissonClient"})
public class CacheClient {

    private final StringRedisTemplate stringRedisTemplate;
    private final RedissonClient redissonClient;

    public void set(String key, Object value, Long time, TimeUnit unit) {
        stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(value), time, unit);
    }

    public void delete(String key) {
        stringRedisTemplate.delete(key);
    }

    public void setWithLogicalExpire(String key, Object value, Long time, TimeUnit unit) {
        RedisData redisData = new RedisData();
        redisData.setData(value);
        redisData.setExpireTime(LocalDateTime.now().plusSeconds(unit.toSeconds(time)));
        stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(redisData));
    }

    public <R, ID> R queryWithPassThrough(
            String keyPrefix, ID id, Class<R> type,
            Function<ID, R> dbFallback, Long time, TimeUnit unit) {
        String key = keyPrefix + id;
        String json = stringRedisTemplate.opsForValue().get(key);
        if (StrUtil.isNotBlank(json)) {
            return JSONUtil.toBean(json, type);
        }
        if (json != null) {
            return null;
        }
        R r = dbFallback.apply(id);
        if (r == null) {
            stringRedisTemplate.opsForValue().set(key, "", CACHE_NULL_TTL, TimeUnit.MINUTES);
            return null;
        }
        this.set(key, r, time, unit);
        return r;
    }

    public <R, ID> R queryWithLogicalExpire(
            String keyPrefix, ID id, Class<R> type,
            Function<ID, R> dbFallback, Long time, TimeUnit unit,
            String lockKeyPrefix) {
        String key = keyPrefix + id;
        String json = stringRedisTemplate.opsForValue().get(key);
        if (StrUtil.isBlank(json)) {
            return null;
        }
        RedisData redisData = JSONUtil.toBean(json, RedisData.class);
        R r = JSONUtil.toBean((String) redisData.getData(), type);
        LocalDateTime expireTime = redisData.getExpireTime();
        if (expireTime.isAfter(LocalDateTime.now())) {
            return r;
        }
        String lockKey = lockKeyPrefix + id;
        RLock lock = redissonClient.getLock(lockKey);
        boolean isLock = lock.tryLock();
        if (isLock) {
            try {
                R newR = dbFallback.apply(id);
                if (newR != null) {
                    this.setWithLogicalExpire(key, newR, time, unit);
                }
            } finally {
                lock.unlock();
            }
        }
        return r;
    }
}