package com.hmall.common.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.hmall.common.utils.RabbitMqHelper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.boot.autoconfigure.AutoConfigureBefore;
import org.springframework.boot.autoconfigure.amqp.RabbitAutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Slf4j
@Configuration
@ConditionalOnClass(name = {"org.springframework.amqp.support.converter.MessageConverter",
        "org.springframework.amqp.rabbit.core.RabbitTemplate"})
@AutoConfigureBefore(RabbitAutoConfiguration.class)
public class MqConfig {

    @Bean
    public MessageConverter messageConverter(ObjectMapper mapper){
        Jackson2JsonMessageConverter jackson2JsonMessageConverter = new Jackson2JsonMessageConverter(mapper);
        jackson2JsonMessageConverter.setCreateMessageIds(true);
        return jackson2JsonMessageConverter;
    }

    @Bean
    public RabbitMqHelper rabbitMqHelper(RabbitTemplate rabbitTemplate){
        return new RabbitMqHelper(rabbitTemplate);
    }

    @Bean
    public static BeanPostProcessor rabbitTemplatePostProcessor() {
        return new BeanPostProcessor() {
            @Override
            public Object postProcessAfterInitialization(Object bean, String beanName) {
                if (bean instanceof RabbitTemplate) {
                    RabbitTemplate rt = (RabbitTemplate) bean;
                    rt.setMandatory(true);
                    rt.setReturnsCallback(returned -> {
                        log.warn("消息路由失败（延迟exchange可能产生此警告），exchange:{}, routingKey:{}, replyCode:{}, replyText:{}, message:{}",
                                returned.getExchange(), returned.getRoutingKey(),
                                returned.getReplyCode(), returned.getReplyText(),
                                new String(returned.getMessage().getBody()));
                    });
                }
                return bean;
            }
        };
    }
}