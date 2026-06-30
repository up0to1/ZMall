package com.hmall.trade.listener;

import com.hmall.common.constants.MqConstants;
import com.hmall.trade.domain.po.Coupon;
import com.hmall.trade.mapper.CouponMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * 优惠券自动下架监听器
 * 优惠期到期自动下架，不能领取/购买
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class CouponOffShelfListener {

    private final CouponMapper couponMapper;

    @RabbitListener(queues = MqConstants.COUPON_OFF_SHELF_DELAY_QUEUE_NAME)
    public void listenCouponOffShelf(Long couponId) {
        log.info("收到优惠券自动下架消息: couponId={}", couponId);

        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon == null) {
            log.info("优惠券不存在，跳过: couponId={}", couponId);
            return;
        }
        // 如果已经是下架状态，忽略
        if (coupon.getStatus() == 0) {
            log.info("优惠券已下架，跳过: couponId={}", couponId);
            return;
        }
        // 如果优惠期还没到期（说明endTime被修改过），忽略此消息
        // 新的endTime会触发新的延迟消息
        if (LocalDateTime.now().isBefore(coupon.getEndTime().minusMinutes(5))) {
            log.info("优惠券endTime已变更，忽略旧消息: couponId={}", couponId);
            return;
        }

        // 执行下架
        coupon.setStatus(0);
        couponMapper.updateById(coupon);
        log.info("优惠券自动下架成功: couponId={}, endTime={}", couponId, coupon.getEndTime());
    }
}
