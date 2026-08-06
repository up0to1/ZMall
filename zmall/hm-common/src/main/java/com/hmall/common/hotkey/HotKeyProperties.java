package com.hmall.common.hotkey;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.concurrent.TimeUnit;

@Data
@ConfigurationProperties(prefix = "hm.hotkey")
public class HotKeyProperties {

    /**
     * 热点判定阈值（统计窗口内访问次数达到该值则视为热点）
     * 默认 50：30 秒窗口内访问 50 次（QPS≈1.67）才判热点，减少低 QPS 误判
     */
    private long threshold = 50;

    /**
     * 热点数据缓存时间
     */
    private long hotCacheTime = 30;

    /**
     * 热点数据缓存时间单位
     */
    private TimeUnit hotCacheUnit = TimeUnit.MINUTES;

    /**
     * 非热点数据缓存时间
     */
    private long warmCacheTime = 5;

    /**
     * 非热点数据缓存时间单位
     */
    private TimeUnit warmCacheUnit = TimeUnit.MINUTES;

    /**
     * 检测间隔（毫秒）：统计窗口长度，也是计数器清理周期
     * 默认 30 秒：平衡热点识别速度与 Redis 压力
     */
    private long detectInterval = 30000;

    /**
     * 热点缓存续期阈值（秒）：当 TTL 低于此值时续期到 hotCacheTime
     * 默认 300 秒 = 5 分钟
     */
    private long refreshBeforeSeconds = 300;
}
