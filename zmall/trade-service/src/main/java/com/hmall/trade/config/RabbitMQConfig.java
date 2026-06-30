package com.hmall.trade.config;

import com.hmall.common.constants.MqConstants;
import org.springframework.amqp.core.*;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class RabbitMQConfig {

    @Bean
    public TopicExchange tradeTopicExchange() {
        return ExchangeBuilder.topicExchange(MqConstants.TRADE_TOPIC_EXCHANGE)
                .durable(true)
                .build();
    }

    @Bean
    public DirectExchange delayExchange() {
        return ExchangeBuilder.directExchange(MqConstants.DELAY_EXCHANGE_NAME)
                .durable(true)
                .delayed()
                .build();
    }

    @Bean
    public Queue delayOrderQueue() {
        return QueueBuilder.durable(MqConstants.DELAY_ORDER_QUEUE_NAME).build();
    }

    @Bean
    public Binding delayOrderBinding() {
        return BindingBuilder.bind(delayOrderQueue()).to(delayExchange()).with(MqConstants.DELAY_ORDER_KEY);
    }

    // ===== 优惠券自动下架延迟队列 =====

    @Bean
    public DirectExchange couponOffShelfDelayExchange() {
        return ExchangeBuilder.directExchange(MqConstants.COUPON_OFF_SHELF_DELAY_EXCHANGE)
                .durable(true)
                .delayed()
                .build();
    }

    @Bean
    public Queue couponOffShelfDelayQueue() {
        return QueueBuilder.durable(MqConstants.COUPON_OFF_SHELF_DELAY_QUEUE_NAME).build();
    }

    @Bean
    public Binding couponOffShelfDelayBinding() {
        return BindingBuilder.bind(couponOffShelfDelayQueue())
                .to(couponOffShelfDelayExchange())
                .with(MqConstants.COUPON_OFF_SHELF_DELAY_KEY);
    }

    // ===== 秒杀商品到期自动转普通商品延迟队列 =====

    @Bean
    public DirectExchange seckillItemExpireDelayExchange() {
        return ExchangeBuilder.directExchange(MqConstants.SECKILL_ITEM_EXPIRE_DELAY_EXCHANGE)
                .durable(true)
                .delayed()
                .build();
    }

    @Bean
    public Queue seckillItemExpireDelayQueue() {
        return QueueBuilder.durable(MqConstants.SECKILL_ITEM_EXPIRE_DELAY_QUEUE_NAME).build();
    }

    @Bean
    public Binding seckillItemExpireDelayBinding() {
        return BindingBuilder.bind(seckillItemExpireDelayQueue())
                .to(seckillItemExpireDelayExchange())
                .with(MqConstants.SECKILL_ITEM_EXPIRE_DELAY_KEY);
    }

    // ===== 秒杀优惠券到期自动下架延迟队列 =====

    @Bean
    public DirectExchange seckillCouponExpireDelayExchange() {
        return ExchangeBuilder.directExchange(MqConstants.SECKILL_COUPON_EXPIRE_DELAY_EXCHANGE)
                .durable(true)
                .delayed()
                .build();
    }

    @Bean
    public Queue seckillCouponExpireDelayQueue() {
        return QueueBuilder.durable(MqConstants.SECKILL_COUPON_EXPIRE_DELAY_QUEUE_NAME).build();
    }

    @Bean
    public Binding seckillCouponExpireDelayBinding() {
        return BindingBuilder.bind(seckillCouponExpireDelayQueue())
                .to(seckillCouponExpireDelayExchange())
                .with(MqConstants.SECKILL_COUPON_EXPIRE_DELAY_KEY);
    }
}