package com.hmall.item.config;

import com.hmall.common.constants.MqConstants;
import org.springframework.amqp.core.*;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 商品同步 MQ 配置（P1-1 修复）
 *
 * 原 ItemServiceImpl.save/updateById/removeById 在事务提交后向 item.sync.exchange
 * 发送商品同步消息，但 Java 侧未声明 exchange，仅依赖 Python 消费者启动时 declare。
 * 风险：RabbitMQ 重启后若 Java 先于 Python 发消息，channel error 导致消息丢失。
 *
 * 修复：在 item-service 启动时由 Spring AMQP 自动声明 exchange + queue + binding，
 * 确保无论 Python 消费者是否启动，exchange 都已存在，Java 发消息不会失败。
 *
 * 注意：queue 与 binding 的参数必须与 Python 侧 item_sync_consumer.py 完全一致，
 * 否则 RabbitMQ 会因参数不匹配抛 PRECONDITION_FAILED。
 */
@Configuration
public class MqConfig {

    // ITEM_SYNC_EXCHANGE / ITEM_SYNC_UPSERT_KEY / ITEM_SYNC_DELETE_KEY 统一引用 MqConstants，避免重复定义
    public static final String ITEM_SYNC_UPSERT_QUEUE = "item.sync.upsert.queue";
    public static final String ITEM_SYNC_DLQ = "item.sync.dlq";
    public static final String ITEM_SYNC_DLQ_KEY = "item.dlq";

    @Bean
    public TopicExchange itemSyncExchange() {
        return ExchangeBuilder.topicExchange(MqConstants.ITEM_SYNC_EXCHANGE).durable(true).build();
    }

    @Bean
    public Queue itemSyncUpsertQueue() {
        // x-dead-letter-exchange + x-dead-letter-routing-key 与 Python 侧一致
        // 失败消息 nack(requeue=False) → DLX(本 exchange) + item.dlq → item.sync.dlq
        return QueueBuilder.durable(ITEM_SYNC_UPSERT_QUEUE)
                .withArgument("x-dead-letter-exchange", MqConstants.ITEM_SYNC_EXCHANGE)
                .withArgument("x-dead-letter-routing-key", ITEM_SYNC_DLQ_KEY)
                .build();
    }

    @Bean
    public Queue itemSyncDlq() {
        // 死信队列：无 DLX 参数，避免死循环
        return QueueBuilder.durable(ITEM_SYNC_DLQ).build();
    }

    @Bean
    public Binding itemSyncUpsertBinding() {
        return BindingBuilder.bind(itemSyncUpsertQueue())
                .to(itemSyncExchange())
                .with(MqConstants.ITEM_SYNC_UPSERT_KEY);
    }

    @Bean
    public Binding itemSyncDeleteBinding() {
        // 单队列绑定两个 routing_key（与 Python 侧一致，由 _on_message 分发）
        return BindingBuilder.bind(itemSyncUpsertQueue())
                .to(itemSyncExchange())
                .with(MqConstants.ITEM_SYNC_DELETE_KEY);
    }

    @Bean
    public Binding itemSyncDlqBinding() {
        return BindingBuilder.bind(itemSyncDlq())
                .to(itemSyncExchange())
                .with(ITEM_SYNC_DLQ_KEY);
    }
}
