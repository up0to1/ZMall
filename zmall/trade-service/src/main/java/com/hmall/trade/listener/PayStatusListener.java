package com.hmall.trade.listener;

import com.hmall.common.constants.MqConstants;
import com.hmall.trade.service.IOrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.amqp.rabbit.annotation.Exchange;
import org.springframework.amqp.rabbit.annotation.Queue;
import org.springframework.amqp.rabbit.annotation.QueueBinding;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class PayStatusListener {

    private final IOrderService orderService;

    @RabbitListener(bindings = @QueueBinding(
            value = @Queue(name = "trade.pay.success.queue", durable = "true"),
            exchange = @Exchange(name = MqConstants.PAY_DIRECT_EXCHANGE),
            key = MqConstants.PAY_SUCCESS_KEY
    ))
    public void listenPaySuccess(Long orderId){

        orderService.markOrderPaySuccess(orderId);
    }
}
