package com.hmall.pay.config;

import com.hmall.common.constants.MqConstants;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.ExchangeBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class RabbitMQConfig {

    @Bean
    public DirectExchange payDirectExchange() {
        return ExchangeBuilder.directExchange(MqConstants.PAY_DIRECT_EXCHANGE)
                .durable(true)
                .build();
    }
}