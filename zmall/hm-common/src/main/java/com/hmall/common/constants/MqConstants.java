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
}