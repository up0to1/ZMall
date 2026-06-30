package com.hmall.common.utils;

import cn.hutool.core.lang.UUID;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.util.concurrent.ListenableFutureCallback;

@Slf4j
@RequiredArgsConstructor
public class RabbitMqHelper {

    private final RabbitTemplate rabbitTemplate;

    public void sendMessage(String exchange, String routingKey, Object msg){
        log.debug("准备发送消息，exchange:{}, routingKey:{}, msg:{}", exchange, routingKey, msg);
        rabbitTemplate.convertAndSend(exchange, routingKey, msg);
    }

    public void sendDelayMessage(String exchange, String routingKey, Object msg, int delay){
        rabbitTemplate.convertAndSend(exchange, routingKey, msg, message -> {
            message.getMessageProperties().setDelay(delay);
            return message;
        });
    }

    public void sendMessageWithConfirm(String exchange, String routingKey, Object msg, int maxRetries){
        doSendWithConfirm(exchange, routingKey, msg, null, maxRetries, 0);
    }

    public void sendDelayMessageWithConfirm(String exchange, String routingKey, Object msg, int delay, int maxRetries){
        doSendWithConfirm(exchange, routingKey, msg, delay, maxRetries, 0);
    }

    private void doSendWithConfirm(String exchange, String routingKey, Object msg, Integer delay, int maxRetries, int retryCount) {
        String msgId = UUID.randomUUID().toString(true);
        log.debug("准备发送消息，exchange:{}, routingKey:{}, msgId:{}, msg:{}", exchange, routingKey, msgId, msg);
        CorrelationData cd = new CorrelationData(msgId);
        cd.getFuture().addCallback(new ListenableFutureCallback<>() {
            @Override
            public void onFailure(Throwable ex) {
                log.error("消息发送异常，msgId:{}, exchange:{}, routingKey:{}", msgId, exchange, routingKey, ex);
            }
            @Override
            public void onSuccess(CorrelationData.Confirm result) {
                if (result.isAck()) {
                    log.debug("消息发送成功，msgId:{}", msgId);
                } else {
                    log.warn("消息发送失败，收到NACK，msgId:{}，当前重试次数：{}", msgId, retryCount);
                    if (retryCount >= maxRetries) {
                        log.error("消息发送重试次数耗尽，msgId:{}，exchange:{}, routingKey:{}", msgId, exchange, routingKey);
                        return;
                    }
                    try {
                        Thread.sleep(500L);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                    doSendWithConfirm(exchange, routingKey, msg, delay, maxRetries, retryCount + 1);
                }
            }
        });
        if (delay != null) {
            rabbitTemplate.convertAndSend(exchange, routingKey, msg, message -> {
                message.getMessageProperties().setDelay(delay);
                return message;
            }, cd);
        } else {
            rabbitTemplate.convertAndSend(exchange, routingKey, msg, cd);
        }
    }
}