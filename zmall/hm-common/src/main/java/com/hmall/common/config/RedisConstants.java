package com.hmall.common.config;

public class RedisConstants {
    public static final String CACHE_ITEM_KEY = "cache:item:";
    public static final Long CACHE_ITEM_TTL = 30L;
    public static final Long CACHE_NULL_TTL = 2L;
    public static final String LOCK_CACHE_ITEM_KEY = "lock:cache:item:";
    public static final Long LOCK_CACHE_ITEM_TTL = 10L;

    public static final String SECKILL_STOCK_KEY = "seckill:item:stock:";
    public static final String SECKILL_ORDER_KEY = "seckill:item:order:";
    public static final String SECKILL_STREAM_KEY = "streams.seckill";
    public static final String LOCK_SECKILL_ORDER_KEY = "lock:seckill:item:order:";
    public static final String SECKILL_ITEM_KEY = "seckill:item:detail:";
    public static final String SECKILL_USER_COUNT_KEY = "seckill:item:user:count:";

    public static final String SECKILL_COUPON_STOCK_KEY = "seckill:coupon:stock:";
    public static final String SECKILL_COUPON_ORDER_KEY = "seckill:coupon:order:";
    public static final String SECKILL_COUPON_USER_COUNT_KEY = "seckill:coupon:user:count:";
    public static final String SECKILL_COUPON_KEY = "seckill:coupon:detail:";

    public static final String FEED_KEY = "feed:";

    public static final String ID_PREFIX_ORDER = "order";
    public static final String ID_PREFIX_SECKILL = "seckill";
    public static final String ID_PREFIX_FEED = "feed";
    public static final String ID_PREFIX_USER_COUPON = "user_coupon";
}