package com.hmall.trade.listener;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.hmall.api.dto.SeckillCouponMessage;
import com.hmall.common.config.RedisConstants;
import com.hmall.common.config.RedisIdWorker;
import com.hmall.common.constants.MqConstants;
import com.hmall.common.utils.RabbitMqHelper;
import com.hmall.trade.domain.po.Coupon;
import com.hmall.trade.domain.po.UserCoupon;
import com.hmall.trade.mapper.CouponMapper;
import com.hmall.trade.mapper.UserCouponMapper;
import com.hmall.trade.service.IOrderService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.concurrent.TimeUnit;

/**
 * 秒杀优惠券订单监听器
 * 消费Redis+Lua判定后的MQ消息
 * - 免费秒杀券：直接创建user_coupon记录
 * - 付费秒杀券：创建优惠券购买订单
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SeckillCouponOrderListener {

    private final UserCouponMapper userCouponMapper;
    private final CouponMapper couponMapper;
    private final RedisIdWorker redisIdWorker;
    private final RedissonClient redissonClient;
    private final IOrderService orderService;

    @RabbitListener(queues = MqConstants.SECKILL_COUPON_ORDER_QUEUE_NAME)
    @Transactional(rollbackFor = Exception.class)
    public void listenSeckillCouponOrder(SeckillCouponMessage message) {
        log.info("收到秒杀优惠券订单消息: couponId={}, userId={}",
                message.getCouponId(), message.getUserId());

        // 1.幂等检查（唯一索引uk_user_coupon保证数据层不重复，这里做前置校验）
        Long existCount = Long.valueOf(userCouponMapper.selectCount(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, message.getUserId())
                        .eq(UserCoupon::getCouponId, message.getCouponId()))) ;
        if (existCount != null && existCount > 0) {
            log.info("用户已领取该秒杀优惠券，跳过: couponId={}, userId={}",
                    message.getCouponId(), message.getUserId());
            return;
        }

        // 2.分布式锁
        RLock lock = redissonClient.getLock(
                "lock:seckill:coupon:create:" + message.getCouponId() + ":" + message.getUserId());
        boolean isLock = false;
        try {
            isLock = lock.tryLock(0, 30, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new RuntimeException("获取锁被中断", e);
        }
        if (!isLock) {
            log.warn("获取锁失败: couponId={}, userId={}", message.getCouponId(), message.getUserId());
            return;
        }
        try {
            // 3.双重检查
            existCount = Long.valueOf(userCouponMapper.selectCount(
                    new LambdaQueryWrapper<UserCoupon>()
                            .eq(UserCoupon::getUserId, message.getUserId())
                            .eq(UserCoupon::getCouponId, message.getCouponId())));
            if (existCount != null && existCount > 0) {
                return;
            }

            // 4.校验优惠券
            Coupon coupon = couponMapper.selectById(message.getCouponId());
            if (coupon == null || coupon.getStatus() != 1) {
                log.warn("优惠券不存在或已停用: couponId={}", message.getCouponId());
                return;
            }

            // 5.根据是否付费分别处理
            if (coupon.getPurchasePrice() != null && coupon.getPurchasePrice() > 0) {
                // 付费秒杀券：创建优惠券购买订单
                Long orderId = orderService.createCouponOrder(
                        message.getCouponId(), message.getUserId(), 3);
                log.info("付费秒杀券创建购买订单: userId={}, couponId={}, orderId={}",
                        message.getUserId(), message.getCouponId(), orderId);
            } else {
                // 免费秒杀券：直接创建user_coupon
                long userCouponId = redisIdWorker.nextId(RedisConstants.ID_PREFIX_USER_COUPON);
                UserCoupon userCoupon = new UserCoupon();
                userCoupon.setId(userCouponId);
                userCoupon.setUserId(message.getUserId());
                userCoupon.setCouponId(message.getCouponId());
                userCoupon.setStatus(1);
                userCoupon.setReceiveTime(LocalDateTime.now());
                if (coupon.getValidDays() != null) {
                    if (coupon.getValidDays() == 0) {
                        userCoupon.setExpireTime(LocalDateTime.now().toLocalDate().atTime(23, 59, 59));
                    } else {
                        userCoupon.setExpireTime(LocalDateTime.now().plusDays(coupon.getValidDays()));
                    }
                }
                userCouponMapper.insert(userCoupon);

                // 更新优惠券已领取数量
                coupon.setReceivedCount(coupon.getReceivedCount() + 1);
                couponMapper.updateById(coupon);

                log.info("免费秒杀券领取成功: userId={}, couponId={}", message.getUserId(), message.getCouponId());
            }
        } finally {
            lock.unlock();
        }
    }
}
