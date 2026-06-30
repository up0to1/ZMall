package com.hmall.trade.schedule;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.hmall.trade.domain.po.Coupon;
import com.hmall.trade.domain.po.Order;
import com.hmall.trade.domain.po.SeckillCoupon;
import com.hmall.trade.domain.po.SeckillItem;
import com.hmall.trade.mapper.CouponMapper;
import com.hmall.trade.mapper.OrderMapper;
import com.hmall.trade.mapper.SeckillCouponMapper;
import com.hmall.trade.mapper.SeckillItemMapper;
import com.hmall.trade.service.IOrderService;
import com.hmall.trade.service.ISeckillService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 定时任务兜底补偿
 * 防止MQ延迟消息丢失导致到期操作未执行
 * 每5分钟扫描一次，补偿处理已过期但未处理的记录
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ScheduledTasks {

    private final OrderMapper orderMapper;
    private final IOrderService orderService;
    private final CouponMapper couponMapper;
    private final SeckillItemMapper seckillItemMapper;
    private final SeckillCouponMapper seckillCouponMapper;
    private final ISeckillService seckillService;

    /**
     * 1. 普通商品订单超时未支付自动取消 - 兜底
     * 扫描状态为1（未支付）且创建时间超过30分钟的普通商品订单
     */
    @Scheduled(fixedDelay = 5 * 60 * 1000)
    public void cancelTimeoutOrders() {
        LocalDateTime threshold = LocalDateTime.now().minusMinutes(30);
        List<Order> orders = orderMapper.selectList(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getStatus, 1)
                        .lt(Order::getCreateTime, threshold)
                        .last("LIMIT 100")
        );
        if (orders.isEmpty()) {
            return;
        }
        log.info("定时兜底：发现{}笔超时未支付订单", orders.size());
        for (Order order : orders) {
            try {
                orderService.cancelOrder(order.getId());
                log.info("定时兜底：订单{}已自动取消", order.getId());
            } catch (Exception e) {
                log.error("定时兜底：订单{}取消失败", order.getId(), e);
            }
        }
    }

    /**
     * 2. 优惠券购买订单超时未支付自动取消 - 兜底
     * 扫描orderType=2（优惠券购买）且status=1（未支付）且创建时间超过30分钟的订单
     * 类似商品购买超时取消，取消后回退秒杀券Redis库存
     */
    @Scheduled(fixedDelay = 5 * 60 * 1000)
    public void cancelTimeoutCouponOrders() {
        LocalDateTime threshold = LocalDateTime.now().minusMinutes(30);
        List<Order> orders = orderMapper.selectList(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getStatus, 1)
                        .eq(Order::getOrderType, 2)
                        .lt(Order::getCreateTime, threshold)
                        .last("LIMIT 100")
        );
        if (orders.isEmpty()) {
            return;
        }
        log.info("定时兜底：发现{}笔超时未支付的优惠券购买订单", orders.size());
        for (Order order : orders) {
            try {
                orderService.cancelOrder(order.getId());
                log.info("定时兜底：优惠券购买订单{}已自动取消", order.getId());
            } catch (Exception e) {
                log.error("定时兜底：优惠券购买订单{}取消失败", order.getId(), e);
            }
        }
    }

    /**
     * 3. 秒杀商品订单超时未支付自动取消 - 兜底
     * 扫描orderType=3（秒杀商品）且status=1（未支付）且创建时间超过15分钟的订单
     */
    @Scheduled(fixedDelay = 5 * 60 * 1000)
    public void cancelTimeoutSeckillOrders() {
        LocalDateTime threshold = LocalDateTime.now().minusMinutes(15);
        List<Order> orders = orderMapper.selectList(
                new LambdaQueryWrapper<Order>()
                        .eq(Order::getStatus, 1)
                        .eq(Order::getOrderType, 3)
                        .lt(Order::getCreateTime, threshold)
                        .last("LIMIT 100")
        );
        if (orders.isEmpty()) {
            return;
        }
        log.info("定时兜底：发现{}笔超时未支付的秒杀商品订单", orders.size());
        for (Order order : orders) {
            try {
                orderService.cancelOrder(order.getId());
                log.info("定时兜底：秒杀商品订单{}已自动取消", order.getId());
            } catch (Exception e) {
                log.error("定时兜底：秒杀商品订单{}取消失败", order.getId(), e);
            }
        }
    }

    /**
     * 4. 优惠券优惠期到期自动下架 - 兜底
     * 扫描状态为1（上架）且结束时间已过的优惠券
     * MQ延迟消息负责到期自动下架，定时任务只兜底"已过期但没下架"的情况
     * 非紧急任务，30分钟扫描一次
     */
    @Scheduled(fixedDelay = 30 * 60 * 1000)
    public void offShelfExpiredCoupons() {
        LocalDateTime now = LocalDateTime.now();
        List<Coupon> coupons = couponMapper.selectList(
                new LambdaQueryWrapper<Coupon>()
                        .eq(Coupon::getStatus, 1)
                        .lt(Coupon::getEndTime, now)
                        .last("LIMIT 100")
        );
        if (coupons.isEmpty()) {
            return;
        }
        log.info("定时兜底：发现{}张优惠期即将到期/已到期的优惠券", coupons.size());
        for (Coupon coupon : coupons) {
            try {
                coupon.setStatus(0);
                couponMapper.updateById(coupon);
                log.info("定时兜底：优惠券{}已自动下架", coupon.getId());
            } catch (Exception e) {
                log.error("定时兜底：优惠券{}下架失败", coupon.getId(), e);
            }
        }
    }

    /**
     * 5. 秒杀商品到期自动转普通商品 - 兜底
     * 扫描抢购结束时间已过的秒杀商品记录
     * 非紧急任务，30分钟扫描一次
     */
    @Scheduled(fixedDelay = 30 * 60 * 1000)
    public void convertExpiredSeckillItems() {
        LocalDateTime now = LocalDateTime.now();
        List<SeckillItem> items = seckillItemMapper.selectList(
                new LambdaQueryWrapper<SeckillItem>()
                        .lt(SeckillItem::getRushEndTime, now)
                        .last("LIMIT 100")
        );
        if (items.isEmpty()) {
            return;
        }
        log.info("定时兜底：发现{}个已过期的秒杀商品", items.size());
        for (SeckillItem item : items) {
            try {
                seckillService.handleSeckillItemExpire(item.getItemId());
                log.info("定时兜底：秒杀商品{}已转为普通商品", item.getItemId());
            } catch (Exception e) {
                log.error("定时兜底：秒杀商品{}转普通商品失败", item.getItemId(), e);
            }
        }
    }

    /**
     * 6. 秒杀优惠券到期自动下架 - 兜底
     * 扫描抢购结束时间已过的秒杀优惠券记录
     * 非紧急任务，30分钟扫描一次
     */
    @Scheduled(fixedDelay = 30 * 60 * 1000)
    public void offShelfExpiredSeckillCoupons() {
        LocalDateTime now = LocalDateTime.now();
        List<SeckillCoupon> coupons = seckillCouponMapper.selectList(
                new LambdaQueryWrapper<SeckillCoupon>()
                        .lt(SeckillCoupon::getRushEndTime, now)
                        .last("LIMIT 100")
        );
        if (coupons.isEmpty()) {
            return;
        }
        log.info("定时兜底：发现{}张已过期的秒杀优惠券", coupons.size());
        for (SeckillCoupon sc : coupons) {
            try {
                seckillService.handleSeckillCouponExpire(sc.getCouponId());
                log.info("定时兜底：秒杀优惠券{}已自动下架", sc.getCouponId());
            } catch (Exception e) {
                log.error("定时兜底：秒杀优惠券{}下架失败", sc.getCouponId(), e);
            }
        }
    }
}
