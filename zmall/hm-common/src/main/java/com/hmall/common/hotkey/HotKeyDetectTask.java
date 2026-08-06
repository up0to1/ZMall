package com.hmall.common.hotkey;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.Cursor;
import org.springframework.data.redis.core.ScanOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ZSetOperations;
import org.springframework.scheduling.annotation.Scheduled;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/**
 * 热点Key检测定时任务
 * <p>
 * 定期清理ZSet访问计数器，重置统计窗口。
 * 同时对已缓存的热点数据延长TTL，保持缓存热度。
 * </p>
 * <p>
 * 性能注意：使用 SCAN 游标迭代替代 KEYS，避免 Redis 单线程阻塞。
 * </p>
 */
@Slf4j
@RequiredArgsConstructor
public class HotKeyDetectTask {

    private static final String COUNTER_KEY_PREFIX = "monitor:hot:";

    private final StringRedisTemplate stringRedisTemplate;
    private final HotKeyProperties properties;

    /**
     * 定时执行：清理计数器 + 刷新热点缓存TTL
     * 间隔由 hm.hotkey.detect-interval 配置，默认 30 秒
     */
    @Scheduled(fixedDelayString = "${hm.hotkey.detect-interval:30000}")
    public void detectAndClean() {
        long startTime = System.currentTimeMillis();
        int counterCount = 0;
        int hotKeyCount = 0;
        int refreshCount = 0;

        try {
            // 使用 SCAN 游标迭代替代 KEYS，避免 Redis 阻塞
            ScanOptions options = ScanOptions.scanOptions()
                    .match(COUNTER_KEY_PREFIX + "*")
                    .count(100)
                    .build();

            List<String> counterKeys = new ArrayList<>();
            try (Cursor<String> cursor = stringRedisTemplate.scan(options)) {
                while (cursor.hasNext()) {
                    counterKeys.add(cursor.next());
                }
            }

            if (counterKeys.isEmpty()) {
                return;
            }

            for (String counterKey : counterKeys) {
                try {
                    int[] result = cleanCounter(counterKey);
                    counterCount++;
                    hotKeyCount += result[0];
                    refreshCount += result[1];
                } catch (Exception e) {
                    log.error("热点计数器清理异常: key={}", counterKey, e);
                }
            }

            // info 级别日志：生产可观测（每 30 秒一条，量不大）
            if (hotKeyCount > 0 || refreshCount > 0) {
                log.info("热点检测完成: 扫描计数器={}, 识别热点={}, 续期={}, 耗时={}ms",
                        counterCount, hotKeyCount, refreshCount, System.currentTimeMillis() - startTime);
            }
        } catch (Exception e) {
            log.warn("热点Key检测任务执行失败，将在下个周期重试: {}", e.getMessage());
        }
    }

    /**
     * 清理单个计数器
     *
     * @return int[2]: [0]=识别的热点数, [1]=续期数
     */
    private int[] cleanCounter(String counterKey) {
        int hotKeyCount = 0;
        int refreshCount = 0;

        // 提取prefix: monitor:hot:cache:item: → cache:item:
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
                    hotKeyCount++;
                    // 热点key：延长其缓存TTL
                    String cacheKey = prefix + key;
                    Long ttl = stringRedisTemplate.getExpire(cacheKey);
                    // 只对即将过期（TTL < 续期阈值）的热点缓存续期
                    if (ttl != null && ttl > 0 && ttl < properties.getRefreshBeforeSeconds()) {
                        stringRedisTemplate.expire(cacheKey, properties.getHotCacheTime(), properties.getHotCacheUnit());
                        refreshCount++;
                        log.info("热点缓存续期: key={}, score={}, ttl={}s → {}{}",
                                cacheKey, score.longValue(), ttl,
                                properties.getHotCacheTime(), properties.getHotCacheUnit());
                    }
                }
            }
        }

        // 删除计数器，重置统计窗口
        stringRedisTemplate.delete(counterKey);

        return new int[]{hotKeyCount, refreshCount};
    }
}
