package com.hmall.trade.listener;

import com.hmall.common.constants.MqConstants;
import com.hmall.trade.domain.po.SeckillCoupon;
import com.hmall.trade.domain.po.SeckillItem;
import com.hmall.trade.mapper.SeckillCouponMapper;
import com.hmall.trade.mapper.SeckillItemMapper;
import com.hmall.trade.service.ISeckillService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * 秒杀到期自动处理监听器
 * - 秒杀商品到期：自动转为普通商品
 * - 秒杀优惠券到期：自动下架
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class SeckillExpireListener {

    private final SeckillItemMapper seckillItemMapper;
    private final SeckillCouponMapper seckillCouponMapper;
    private final ISeckillService seckillService;

    /**
     * 秒杀商品到期：自动转为普通商品
     */
    @RabbitListener(queues = MqConstants.SECKILL_ITEM_EXPIRE_DELAY_QUEUE_NAME)
    public void listenSeckillItemExpire(Long itemId) {
        log.info("收到秒杀商品到期消息: itemId={}", itemId);

        SeckillItem seckillItem = seckillItemMapper.selectById(itemId);
        if (seckillItem == null) {
            log.info("秒杀商品记录不存在，可能已处理: itemId={}", itemId);
            return;
        }

        // 校验是否真的到期（防止时间被修改后旧消息触发）
        LocalDateTime now = LocalDateTime.now();
        if (now.isBefore(seckillItem.getRushEndTime())) {
            log.info("秒杀商品尚未到期，忽略旧消息: itemId={}, rushEndTime={}", itemId, seckillItem.getRushEndTime());
            return;
        }

        // 转为普通商品
        seckillService.handleSeckillItemExpire(itemId);
    }

    /**
     * 秒杀优惠券到期：自动下架
     */
    @RabbitListener(queues = MqConstants.SECKILL_COUPON_EXPIRE_DELAY_QUEUE_NAME)
    public void listenSeckillCouponExpire(Long couponId) {
        log.info("收到秒杀优惠券到期消息: couponId={}", couponId);

        SeckillCoupon seckillCoupon = seckillCouponMapper.selectById(couponId);
        if (seckillCoupon == null) {
            log.info("秒杀优惠券记录不存在，可能已处理: couponId={}", couponId);
            return;
        }

        // 校验是否真的到期
        LocalDateTime now = LocalDateTime.now();
        if (now.isBefore(seckillCoupon.getRushEndTime())) {
            log.info("秒杀优惠券尚未到期，忽略旧消息: couponId={}, rushEndTime={}", couponId, seckillCoupon.getRushEndTime());
            return;
        }

        // 自动下架
        seckillService.handleSeckillCouponExpire(couponId);
    }
}
