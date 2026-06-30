package com.hmall.cart.listener;

import com.hmall.api.dto.CartClearMessageDTO;
import com.hmall.cart.service.ICartService;
import com.hmall.common.constants.MqConstants;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.core.ExchangeTypes;
import org.springframework.amqp.rabbit.annotation.Exchange;
import org.springframework.amqp.rabbit.annotation.Queue;
import org.springframework.amqp.rabbit.annotation.QueueBinding;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.concurrent.TimeUnit;

@Slf4j
@Component
@RequiredArgsConstructor
public class ClearCartListener {

    private final ICartService cartService;
    private final StringRedisTemplate stringRedisTemplate;

    private static final String CART_CLEARED_KEY_PREFIX = "cart:cleared:";
    private static final long CART_CLEARED_TTL_HOURS = 24;

    @RabbitListener(bindings = @QueueBinding(
            value = @Queue(name = "cart.clear.queue", durable = "true"),
            exchange = @Exchange(name = MqConstants.TRADE_TOPIC_EXCHANGE, type = ExchangeTypes.TOPIC),
            key = MqConstants.ORDER_CREATE_KEY
    ))
    public void listenClearCart(CartClearMessageDTO message) {
        // 幂等检查：用Redis key标记该订单已清理购物车，防止重复消费误删用户新加的购物车项
        String dedupKey = CART_CLEARED_KEY_PREFIX + message.getOrderId();
        Boolean isFirst = stringRedisTemplate.opsForValue().setIfAbsent(dedupKey, "1", CART_CLEARED_TTL_HOURS, TimeUnit.HOURS);
        if (Boolean.FALSE.equals(isFirst)) {
            log.info("购物车清理已处理，跳过重复消费: orderId={}", message.getOrderId());
            return;
        }

        cartService.removeByItemIds(message.getUserId(), message.getItemIds());
        log.info("购物车清理完成: orderId={}, userId={}", message.getOrderId(), message.getUserId());
    }
}
