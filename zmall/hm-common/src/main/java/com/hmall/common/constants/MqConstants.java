package com.hmall.common.constants;

public interface MqConstants {

    String DELAY_EXCHANGE_NAME = "trade.delay.direct";
    String DELAY_ORDER_QUEUE_NAME = "trade.delay.order.queue";
    String DELAY_ORDER_KEY = "delay.order.query";

    String TRADE_TOPIC_EXCHANGE = "trade.topic";
    String ORDER_CREATE_KEY = "order.create";

    String PAY_DIRECT_EXCHANGE = "pay.direct";
    String PAY_SUCCESS_KEY = "pay.success";

    String SECKILL_DIRECT_EXCHANGE = "seckill.direct";
    String SECKILL_ORDER_QUEUE_NAME = "seckill.order.queue";
    String SECKILL_ORDER_KEY = "seckill.order";

    String SECKILL_DELAY_EXCHANGE = "seckill.delay.direct";
    String SECKILL_DELAY_QUEUE_NAME = "seckill.delay.order.queue";
    String SECKILL_DELAY_KEY = "seckill.delay.order";

    // 秒杀优惠券 MQ
    String SECKILL_COUPON_ORDER_QUEUE_NAME = "seckill.coupon.order.queue";
    String SECKILL_COUPON_ORDER_KEY = "seckill.coupon.order";

    String SHOP_FEED_DIRECT_EXCHANGE = "shop.feed.direct";
    String SHOP_FEED_QUEUE_NAME = "shop.feed.queue";
    String SHOP_FEED_KEY = "shop.feed";

    // 优惠券自动下架 MQ
    String COUPON_OFF_SHELF_DELAY_EXCHANGE = "coupon.offshelf.delay.direct";
    String COUPON_OFF_SHELF_DELAY_QUEUE_NAME = "coupon.offshelf.delay.queue";
    String COUPON_OFF_SHELF_DELAY_KEY = "coupon.offshelf.delay";

    // 秒杀商品到期自动转普通商品 MQ
    String SECKILL_ITEM_EXPIRE_DELAY_EXCHANGE = "seckill.item.expire.delay.direct";
    String SECKILL_ITEM_EXPIRE_DELAY_QUEUE_NAME = "seckill.item.expire.delay.queue";
    String SECKILL_ITEM_EXPIRE_DELAY_KEY = "seckill.item.expire.delay";

    // 秒杀优惠券到期自动下架 MQ
    String SECKILL_COUPON_EXPIRE_DELAY_EXCHANGE = "seckill.coupon.expire.delay.direct";
    String SECKILL_COUPON_EXPIRE_DELAY_QUEUE_NAME = "seckill.coupon.expire.delay.queue";
    String SECKILL_COUPON_EXPIRE_DELAY_KEY = "seckill.coupon.expire.delay";

    // ===== AI 功能 MQ =====
    /** AI 随心搭结果回流（Python → Java user-service 消费，做配额确认/回滚） */
    String AI_OUTFIT_EXCHANGE = "ai.outfit.exchange";
    String AI_OUTFIT_RESULT_QUEUE = "ai.outfit.result.queue";
    String AI_OUTFIT_RESULT_KEY = "ai.outfit.result";

    /** AI 模特图生成任务下发（Java item-service → Python ai-models 消费） */
    String AI_MODEL_EXCHANGE = "ai.model.exchange";
    String AI_MODEL_GENERATE_KEY = "ai.model.generate";
    /** AI 模特图结果回流（Python → Java item-service 消费） */
    String AI_MODEL_RESULT_QUEUE = "ai.model.result.queue";
    String AI_MODEL_RESULT_KEY = "ai.model.result";

    /** 商品库同步（Java item-service → Python ai-outfit 消费，写 Qdrant 向量库） */
    String ITEM_SYNC_EXCHANGE = "item.sync.exchange";
    String ITEM_SYNC_UPSERT_KEY = "item.upsert";
    String ITEM_SYNC_DELETE_KEY = "item.delete";

    // ===== 用户行为事件（Phase 2.5 个性化推荐画像数据源）=====
    /** 用户行为事件 Exchange（Java item/cart/trade + Python ai-outfit → Python UserBehaviorConsumer 消费） */
    String USER_BEHAVIOR_EXCHANGE = "user.behavior.exchange";
    /** Routing Key 前缀，完整格式：user.behavior.{type}（如 user.behavior.ITEM_VIEW） */
    String USER_BEHAVIOR_KEY_PREFIX = "user.behavior.";
    /** 行为类型（用于拼接 routing key，OUTFIT_ACCEPT 由 Python 侧直接发送，Java 不引用） */
    String BEHAVIOR_TYPE_ITEM_VIEW = "ITEM_VIEW";
    String BEHAVIOR_TYPE_CART_ADD = "CART_ADD";
    String BEHAVIOR_TYPE_ORDER_PLACE = "ORDER_PLACE";

    // ===== AI 任务结果回流幂等 Redis Key 前缀 =====
    /**
     * AI 模特任务结果幂等 key 前缀（item-service AiTaskServiceImpl + AiTaskTimeoutScheduler 共用）
     * 完整 key: ai:task:result:{taskId}，TTL 1 小时
     */
    String AI_TASK_RESULT_IDEMPOTENT_PREFIX = "ai:task:result:";
}