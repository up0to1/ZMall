package com.hmall.trade.listener;

import com.hmall.api.client.PayClient;
import com.hmall.api.dto.PayOrderDTO;
import com.hmall.common.constants.MqConstants;
import com.hmall.trade.domain.po.Order;
import com.hmall.trade.mapper.OrderMapper;
import com.hmall.trade.service.IOrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
public class OrderDelayMessageListener {
    private final IOrderService orderService;
    private final OrderMapper orderMapper;
    private final PayClient payClient;

    @RabbitListener(queues = MqConstants.DELAY_ORDER_QUEUE_NAME)
    public void listenOrderDelayMessage(Long orderId){
        // 1.查询订单
        Order order = orderMapper.selectById(orderId);
        // 2.检测订单状态，判断是否已支付
        if(order == null || order.getStatus() != 1){
            // 订单不存在或者已经支付
            return;
        }
        // 3.未支付，需要查询支付流水状态
        PayOrderDTO payOrder = payClient.queryPayOrderByBizOrderNo(orderId);
        // 4.判断是否支付
        if(payOrder != null && payOrder.getStatus() == 3){
            // 4.1.已支付，标记订单状态为已支付
            orderService.markOrderPaySuccess(orderId);
        }else{
            orderService.cancelOrder(orderId);
        }
    }
}
