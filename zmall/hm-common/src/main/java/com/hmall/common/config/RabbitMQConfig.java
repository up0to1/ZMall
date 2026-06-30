package com.hmall.common.config;

import com.hmall.common.constants.MqConstants;
import org.springframework.amqp.core.*;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@ConditionalOnClass(name = "org.springframework.amqp.core.Exchange")
public class RabbitMQConfig {

    @Bean
    @ConditionalOnProperty(name = "hm.mq.seckill.enabled", havingValue = "true")
    public DirectExchange seckillDirectExchange() {
        return ExchangeBuilder.directExchange(MqConstants.SECKILL_DIRECT_EXCHANGE)
                .durable(true)
                .build();
    }

    @Bean
    @ConditionalOnProperty(name = "hm.mq.seckill.enabled", havingValue = "true")
    public Queue seckillOrderQueue() {
        return QueueBuilder.durable(MqConstants.SECKILL_ORDER_QUEUE_NAME).build();
    }

    @Bean
    @ConditionalOnProperty(name = "hm.mq.seckill.enabled", havingValue = "true")
    public Binding seckillOrderBinding() {
        return BindingBuilder.bind(seckillOrderQueue())
                .to(seckillDirectExchange())
                .with(MqConstants.SECKILL_ORDER_KEY);
    }

    @Bean
    @ConditionalOnProperty(name = "hm.mq.seckill.enabled", havingValue = "true")
    public org.springframework.amqp.core.Exchange seckillDelayExchange() {
        return ExchangeBuilder.directExchange(MqConstants.SECKILL_DELAY_EXCHANGE)
                .durable(true)
                .delayed()
                .build();
    }

    @Bean
    @ConditionalOnProperty(name = "hm.mq.seckill.enabled", havingValue = "true")
    public Queue seckillDelayQueue() {
        return QueueBuilder.durable(MqConstants.SECKILL_DELAY_QUEUE_NAME).build();
    }

    @Bean
    @ConditionalOnProperty(name = "hm.mq.seckill.enabled", havingValue = "true")
    public Binding seckillDelayBinding() {
        return BindingBuilder.bind(seckillDelayQueue())
                .to(seckillDelayExchange())
                .with(MqConstants.SECKILL_DELAY_KEY)
                .noargs();
    }

    // ===== 秒杀优惠券 MQ =====

    @Bean
    @ConditionalOnProperty(name = "hm.mq.seckill.enabled", havingValue = "true")
    public Queue seckillCouponOrderQueue() {
        return QueueBuilder.durable(MqConstants.SECKILL_COUPON_ORDER_QUEUE_NAME).build();
    }

    @Bean
    @ConditionalOnProperty(name = "hm.mq.seckill.enabled", havingValue = "true")
    public Binding seckillCouponOrderBinding() {
        return BindingBuilder.bind(seckillCouponOrderQueue())
                .to(seckillDirectExchange())
                .with(MqConstants.SECKILL_COUPON_ORDER_KEY);
    }

    @Bean
    @ConditionalOnProperty(name = "hm.mq.shop-feed.enabled", havingValue = "true")
    public DirectExchange shopFeedDirectExchange() {
        return ExchangeBuilder.directExchange(MqConstants.SHOP_FEED_DIRECT_EXCHANGE)
                .durable(true)
                .build();
    }

    @Bean
    @ConditionalOnProperty(name = "hm.mq.shop-feed.enabled", havingValue = "true")
    public Queue shopFeedQueue() {
        return QueueBuilder.durable(MqConstants.SHOP_FEED_QUEUE_NAME).build();
    }

    @Bean
    @ConditionalOnProperty(name = "hm.mq.shop-feed.enabled", havingValue = "true")
    public Binding shopFeedBinding() {
        return BindingBuilder.bind(shopFeedQueue())
                .to(shopFeedDirectExchange())
                .with(MqConstants.SHOP_FEED_KEY);
    }
}
