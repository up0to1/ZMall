package com.hmall.common.hotkey;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.scheduling.annotation.Scheduled;

import java.util.Set;

/**
 * 热点Key检测定时任务
 * <p>
 * 定期清理ZSet访问计数器，重置统计窗口。
 * 同时对已缓存的热点数据延长TTL，保持缓存热度。
 * </p>
 */
@Slf4j
@RequiredArgsConstructor
public class HotKeyDetectTask {

    private static final String COUNTER_KEY_PREFIX = "monitor:hot:";

    private final StringRedisTemplate stringRedisTemplate;
    private final HotKeyProperties properties;

    /**
     * 每10秒执行一次：清理计数器 + 刷新热点缓存TTL
     */
    @Scheduled(fixedDelayString = "${hm.hotkey.detect-interval:10000}")
    public void detectAndClean() {
        try {
            Set<String> counterKeys = stringRedisTemplate.keys(COUNTER_KEY_PREFIX + "*");
            if (counterKeys == null || counterKeys.isEmpty()) {
                return;
            }

            for (String counterKey : counterKeys) {
                try {
                    cleanCounter(counterKey);
                } catch (Exception e) {
                    log.error("热点计数器清理异常: key={}", counterKey, e);
                }
            }
        } catch (Exception e) {
            log.warn("热点Key检测任务执行失败，将在下个周期重试: {}", e.getMessage());
        }
    }

    private void cleanCounter(String counterKey) {
        // 提取prefix: hot:counter:cache:item: → cache:item:
        String prefix = counterKey.substring(COUNTER_KEY_PREFIX.length());

        // 获取所有热点key（score >= 阈值）
        Set<ZSetOperations.TypedTuple<String>> hotKeys = stringRedisTemplate.opsForZSet()
                .reverseRangeWithScores(counterKey, 0, -1);

        if (hotKeys != null) {
            for (ZSetOperations.TypedTuple<String> tuple : hotKeys) {
                String key = tuple.getValue();
                Double score = tuple.getScore();
                if (key == null || score == null) continue;

                if (score >= properties.getThreshold()) {
                    // 热点key：延长其缓存TTL
                    String cacheKey = prefix + key;
                    Long ttl = stringRedisTemplate.getExpire(cacheKey);
                    // 只对即将过期（TTL < 5分钟）的热点缓存续期
                    if (ttl != null && ttl > 0 && ttl < properties.getRefreshBeforeMin()) {
                        stringRedisTemplate.expire(cacheKey, properties.getHotCacheTime(), properties.getHotCacheUnit());
                        log.debug("热点缓存续期: key={}, score={}, newTTL={}{}",
                                cacheKey, score, properties.getHotCacheTime(), properties.getHotCacheUnit());
                    }
                }
            }
        }

        // 删除计数器，重置统计窗口
        stringRedisTemplate.delete(counterKey);
    }
}
