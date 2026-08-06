package com.hmall.item.listener;

import com.hmall.api.dto.AiModelResultMessage;
import com.hmall.common.constants.MqConstants;
import com.hmall.item.metrics.AiMetrics;
import com.hmall.item.service.IAiTaskService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.core.ExchangeTypes;
import org.springframework.amqp.rabbit.annotation.Exchange;
import org.springframework.amqp.rabbit.annotation.Queue;
import org.springframework.amqp.rabbit.annotation.QueueBinding;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

/**
 * AI 模特图结果回流监听器
 *
 * Python ai-models 完成模特图生成后，向 ai.model.exchange 发送结果消息。
 * item-service 消费 ai.model.result 队列，更新 ai_task 表 + 配额确认/回滚。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AiModelResultListener {

    private final IAiTaskService aiTaskService;
    private final AiMetrics aiMetrics;

    @RabbitListener(bindings = @QueueBinding(
            value = @Queue(name = MqConstants.AI_MODEL_RESULT_QUEUE, durable = "true"),
            exchange = @Exchange(name = MqConstants.AI_MODEL_EXCHANGE, type = ExchangeTypes.TOPIC),
            key = MqConstants.AI_MODEL_RESULT_KEY
    ))
    public void listenModelResult(AiModelResultMessage message) {
        log.info("收到 AI 模特图结果消息: taskId={}, status={}, shopId={}",
                message.getTaskId(), message.getStatus(), message.getShopId());
        try {
            aiTaskService.handleModelResult(message);
        } catch (Exception e) {
            // 异常仅记录日志，不抛出（避免消息无限重投，依赖定时任务对账）
            log.error("处理模特图结果异常: taskId={}, error={}",
                    message.getTaskId(), e.getMessage(), e);
            aiMetrics.recordMqConsumeFailure(MqConstants.AI_MODEL_RESULT_QUEUE);
        }
    }
}
