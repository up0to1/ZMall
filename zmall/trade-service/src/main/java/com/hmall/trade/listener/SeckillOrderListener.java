package com.hmall.trade.listener;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.hmall.api.client.ItemClient;
import com.hmall.api.dto.ItemDTO;
import com.hmall.common.constants.MqConstants;
import com.hmall.trade.domain.dto.SeckillOrderMessage;
import com.hmall.trade.domain.po.Order;
import com.hmall.trade.domain.po.OrderDetail;
import com.hmall.trade.domain.po.SeckillItem;
import com.hmall.trade.mapper.OrderDetailMapper;
import com.hmall.trade.mapper.OrderMapper;
import com.hmall.trade.mapper.SeckillItemMapper;
import com.hmall.trade.service.IOrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * 秒杀商品订单监听器
 * 消费Redis+Lua判定后的MQ消息，直接创建正式订单（orderType=3）
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SeckillOrderListener {

    private final OrderMapper orderMapper;
    private final SeckillItemMapper seckillItemMapper;
    private final OrderDetailMapper detailMapper;
    private final RedissonClient redissonClient;
    private final IOrderService orderService;
    private final ItemClient itemClient;

    @RabbitListener(queues = MqConstants.SECKILL_ORDER_QUEUE_NAME)
    public void listenSeckillOrder(SeckillOrderMessage message) {
        log.debug("收到秒杀订单消息: orderId={}, userId={}, itemId={}",
                message.getOrderId(), message.getUserId(), message.getItemId());

        // 1.幂等检查：正式订单是否已创建
        Order existOrder = orderMapper.selectById(message.getOrderId());
        if (existOrder != null) {
            log.info("秒杀正式订单已存在，跳过: orderId={}", message.getOrderId());
            return;
        }

        // 2.分布式锁
        RLock lock = redissonClient.getLock("lock:seckill:order:create:" + message.getOrderId());
        boolean isLock = false;
        try {
            isLock = lock.tryLock(0, 30, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new RuntimeException("获取锁被中断", e);
        }
        if (!isLock) {
            log.warn("获取锁失败: orderId={}", message.getOrderId());
            return;
        }
        try {
            // 3.双重检查
            existOrder = orderMapper.selectById(message.getOrderId());
            if (existOrder != null) {
                return;
            }

            // 4.校验商品必须是秒杀商品
            ItemDTO item = itemClient.queryItemById(message.getItemId());
            if (item == null || item.getItemType() == null || item.getItemType() != 2) {
                log.warn("商品不是秒杀商品，跳过: itemId={}, orderId={}", message.getItemId(), message.getOrderId());
                return;
            }

            // 5.校验限购数量（基于正式订单表，按特定商品过滤）
            SeckillItem seckillItem = seckillItemMapper.selectById(message.getItemId());
            int maxPerUser = seckillItem != null && seckillItem.getMaxPerUser() != null
                    ? seckillItem.getMaxPerUser() : 1;
            // 查询该用户购买该特定秒杀商品的未取消订单数
            List<Order> userSeckillOrders = orderMapper.selectList(
                    new LambdaQueryWrapper<Order>()
                            .eq(Order::getUserId, message.getUserId())
                            .eq(Order::getOrderType, 3)
                            .ne(Order::getStatus, 5));
            long boughtCount = 0;
            for (Order o : userSeckillOrders) {
                Long detailCount = Long.valueOf(detailMapper.selectCount(
                        new LambdaQueryWrapper<OrderDetail>()
                                .eq(OrderDetail::getOrderId, o.getId())
                                .eq(OrderDetail::getItemId, message.getItemId()))) ;
                if (detailCount != null && detailCount > 0) {
                    boughtCount++;
                }
            }
            if (boughtCount >= maxPerUser) {
                log.warn("超出限购数量: orderId={}, itemId={}, boughtCount={}, maxPerUser={}",
                        message.getOrderId(), message.getItemId(), boughtCount, maxPerUser);
                return;
            }

            // 6.直接创建正式订单（使用秒杀价）
            int seckillPrice = seckillItem != null ? seckillItem.getSeckillPrice() : item.getPrice();
            orderService.createSeckillOrder(
                    message.getOrderId(), message.getUserId(), message.getItemId(), 1, seckillPrice, message.getCouponId());

            // 7.更新已售库存 sold_stock++
            seckillItemMapper.update(null,
                    new LambdaUpdateWrapper<SeckillItem>()
                            .eq(SeckillItem::getItemId, message.getItemId())
                            .setSql("sold_stock = sold_stock + 1"));

            log.info("秒杀正式订单创建成功: orderId={}", message.getOrderId());
        } finally {
            lock.unlock();
        }
    }
}
