package com.hmall.common.hotkey;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.concurrent.TimeUnit;

@Data
@ConfigurationProperties(prefix = "hm.hotkey")
public class HotKeyProperties {

    /**
     * 热点判定阈值（统计窗口内访问次数）
     */
    private long threshold = 10;

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
     * 检测间隔（毫秒）
     */
    private long detectInterval = 10000;

    /**
     * 热点缓存续期阈值：当TTL低于此值（秒）时续期
     */
    private long refreshBeforeMin = 300;
}
