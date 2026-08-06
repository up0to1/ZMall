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

    // ===== AI 配额（旧版·次数制，仅 MODEL 使用）=====
    /** 当日剩余免费次数: ai:quota:free:{type}:{id}:{date} */
    public static final String AI_QUOTA_FREE_KEY = "ai:quota:free:";
    /** 付费余额: ai:quota:paid:{type}:{id} */
    public static final String AI_QUOTA_PAID_KEY = "ai:quota:paid:";
    /** 预扣冻结记录: ai:quota:frozen:{type}:{id}:{taskId} */
    public static final String AI_QUOTA_FROZEN_KEY = "ai:quota:frozen:";
    /** 冻结记录 TTL: 10 分钟 */
    public static final Long AI_QUOTA_FROZEN_TTL = 600L;
    /** 每日免费额度 */
    public static final int AI_QUOTA_DAILY_FREE = 10;

    // ===== AI Credits（v3·积分制，OUTFIT_RECOMMEND/OUTFIT_VTON 使用）=====
    /**
     * 赠送 credits 明细: ai:credits:free:{userId}
     * Hash 结构：field=过期时间戳（秒）, value=该批次剩余数量
     * FIFO 扣减：按 field（过期时间）升序扣减，过期自动清理
     * 30 天有效期，充值/赠送时按批次写入
     */
    public static final String AI_CREDITS_FREE_KEY = "ai:credits:free:";
    /** 充值 credits 余额（永久有效）: ai:credits:paid:{userId} → string 总数 */
    public static final String AI_CREDITS_PAID_KEY = "ai:credits:paid:";
    /**
     * 预扣冻结记录: ai:credits:frozen:{userId}:{taskId}
     * value=JSON 明细 {free:{expireTs:count}, paid:int, total:int, phase:str}
     * rollback 时按原路返还（free 返还到原 expireTs 批次，paid 直接累加）
     */
    public static final String AI_CREDITS_FROZEN_KEY = "ai:credits:frozen:";
    /** Credits 冻结记录 TTL: 30 分钟（覆盖 VTON 多套生成 + WS 重试窗口）*/
    public static final Long AI_CREDITS_FROZEN_TTL = 1800L;
    /** 首次使用 AI 随心搭赠送 credits 数量（US-AT-32）*/
    public static final int AI_CREDITS_GIFT_AMOUNT = 50;
    /** 赠送 credits 有效期：30 天（秒）*/
    public static final Long AI_CREDITS_FREE_TTL = 30 * 24 * 3600L;
    /** 评分激励：≥4★+发布奖励 credits 数量 */
    public static final int AI_CREDITS_AWARD_RATING = 1;
    /** 评分激励：拒绝原因 ≥20 字奖励 credits 数量 */
    public static final int AI_CREDITS_AWARD_REJECT = 1;
    /** 评分激励：每日奖励上限（≥4★+发布）*/
    public static final int AI_CREDITS_AWARD_RATING_DAILY_LIMIT = 5;
    /** 评分激励：每日奖励上限（拒绝原因）*/
    public static final int AI_CREDITS_AWARD_REJECT_DAILY_LIMIT = 3;
    /** 充值汇率：1 元 = 5 credits（US-AT-33）*/
    public static final int AI_CREDITS_RATE_YUAN_TO_CREDITS = 5;
    /** 阶段一候选推荐扣减 credits 数（v3 设计）*/
    public static final int AI_CREDITS_PHASE_CANDIDATE = 2;
    /** 阶段二 VTON 生成单套扣减 credits 数（v3 设计，按套数 N 倍扣）*/
    public static final int AI_CREDITS_PHASE_VTON_PER_OUTFIT = 5;
}