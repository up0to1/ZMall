package com.hmall.common.hotkey;

import java.lang.annotation.*;
import java.util.concurrent.TimeUnit;

/**
 * 热点Key自动缓存注解
 * <p>
 * 标记在查询方法上，自动统计访问频率，当访问量达到阈值时自动缓存到Redis。
 * 低频访问数据使用短TTL缓存，高频访问数据使用长TTL缓存。
 * </p>
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
@Documented
public @interface HotKeyCache {

    /**
     * 缓存key前缀，如 "cache:item:"
     */
    String prefix();

    /**
     * 用作key的方法参数索引（从0开始），默认取第0个参数
     */
    int keyParamIndex() default 0;

    /**
     * 热点判定阈值：在统计窗口内访问次数达到该值则视为热点
     */
    long threshold() default 10;

    /**
     * 热点数据缓存时间
     */
    long hotCacheTime() default 30;

    /**
     * 热点数据缓存时间单位，默认分钟
     */
    TimeUnit hotCacheUnit() default TimeUnit.MINUTES;

    /**
     * 非热点数据缓存时间（温缓存，避免冷数据反复穿透）
     */
    long warmCacheTime() default 5;

    /**
     * 非热点数据缓存时间单位，默认分钟
     */
    TimeUnit warmCacheUnit() default TimeUnit.MINUTES;
}
