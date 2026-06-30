package com.hmall.common.hotkey;

import cn.hutool.core.util.StrUtil;
import cn.hutool.json.JSONUtil;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.aspectj.lang.reflect.MethodSignature;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.util.concurrent.TimeUnit;

/**
 * 热点Key缓存切面
 * <p>
 * 拦截标注了 @HotKeyCache 的方法，实现：
 * 1. 通过 Redis ZSet 统计访问频次
 * 2. 优先从缓存读取数据
 * 3. 缓存未命中时执行原方法，根据访问频次决定缓存TTL
 * </p>
 */
@Slf4j
@Aspect
@RequiredArgsConstructor
public class HotKeyCacheAspect {

    private static final String COUNTER_KEY_PREFIX = "monitor:hot:";

    private final StringRedisTemplate stringRedisTemplate;

    @Around("@annotation(hotKeyCache)")
    public Object around(ProceedingJoinPoint pjp, HotKeyCache hotKeyCache) throws Throwable {
        // 1. 提取缓存key
        Object[] args = pjp.getArgs();
        Object keyValue = args[hotKeyCache.keyParamIndex()];
        String keyStr = String.valueOf(keyValue);
        String cacheKey = hotKeyCache.prefix() + keyStr;
        String counterKey = COUNTER_KEY_PREFIX + hotKeyCache.prefix();

        // 2. ZSet计数+1
        Double score = stringRedisTemplate.opsForZSet().incrementScore(counterKey, keyStr, 1);

        // 3. 判断是否为热点
        boolean isHot = score != null && score >= hotKeyCache.threshold();

        // 4. 尝试从缓存获取
        String json = stringRedisTemplate.opsForValue().get(cacheKey);
        if (StrUtil.isNotBlank(json)) {
            Class<?> returnType = ((MethodSignature) pjp.getSignature()).getReturnType();
            return JSONUtil.toBean(json, returnType);
        }
        // 空值缓存命中
        if (json != null) {
            return null;
        }

        // 5. 缓存未命中，执行原方法
        Object result = pjp.proceed();

        // 6. 根据热点状态决定缓存策略
        if (result != null) {
            long ttl = isHot ? hotKeyCache.hotCacheTime() : hotKeyCache.warmCacheTime();
            TimeUnit unit = isHot ? hotKeyCache.hotCacheUnit() : hotKeyCache.warmCacheUnit();
            stringRedisTemplate.opsForValue().set(cacheKey, JSONUtil.toJsonStr(result), ttl, unit);
            if (isHot) {
                log.debug("热点Key缓存写入: key={}, score={}, ttl={}{}", cacheKey, score, ttl, unitToString(unit));
            }
        } else {
            // 空值缓存，短TTL防穿透
            stringRedisTemplate.opsForValue().set(cacheKey, "", 2L, TimeUnit.MINUTES);
        }

        return result;
    }

    private String unitToString(TimeUnit unit) {
        if (unit == TimeUnit.MINUTES) return "min";
        if (unit == TimeUnit.SECONDS) return "s";
        if (unit == TimeUnit.HOURS) return "h";
        return unit.toString();
    }
}
