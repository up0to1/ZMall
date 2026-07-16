package com.hmall.trade.schedule;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.hmall.common.config.RedisConstants;
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
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
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
    private final StringRedisTemplate stringRedisTemplate;

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
     * 扫描orderType=3（秒杀商品）且status=1（未支付）且创建时间超过30分钟的订单
     */
    @Scheduled(fixedDelay = 5 * 60 * 1000)
    public void cancelTimeoutSeckillOrders() {
        LocalDateTime threshold = LocalDateTime.now().minusMinutes(30);
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

    /**
     * 7. 秒杀商品自动预热 - 开抢前5分钟自动写入Redis
     * 扫描即将开抢(5分钟内)或已开抢但未过期的秒杀商品
     * - 若Redis中尚未预热则自动预热
     * - 若已预热，则同步DB实际剩余可秒杀库存（seckill_stock - sold_stock）
     * 兜底：防止秒杀开始前没来得及自动把预热写入redis，已开抢的也补预热
     */
    @Scheduled(fixedDelay = 60 * 1000)
    public void autoPreheatSeckillItems() {
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime preheatWindow = now.plusMinutes(5);
        List<SeckillItem> items = seckillItemMapper.selectList(
                new LambdaQueryWrapper<SeckillItem>()
                        .le(SeckillItem::getRushBeginTime, preheatWindow)
                        .gt(SeckillItem::getRushEndTime, now)
                        .last("LIMIT 100")
        );
        if (items.isEmpty()) {
            return;
        }
        int count = 0;
        for (SeckillItem item : items) {
            try {
                String stockKey = RedisConstants.SECKILL_STOCK_KEY + item.getItemId();
                Boolean exists = stringRedisTemplate.hasKey(stockKey);
                if (Boolean.FALSE.equals(exists)) {
                    seckillService.preheatStockToRedis(item.getItemId());
                    count++;
                    log.info("定时自动预热：秒杀商品{}已预热", item.getItemId());
                } else {
                    // 已预热：同步DB实际剩余可秒杀库存 = 总库存 - 已售库存
                    long ttlSeconds = Duration.between(now, item.getRushEndTime()).getSeconds();
                    if (ttlSeconds <= 0) continue;
                    int dbStock = item.getSeckillStock() != null ? item.getSeckillStock() : 0;
                    int soldStock = item.getSoldStock() != null ? item.getSoldStock() : 0;
                    int remaining = Math.max(0, dbStock - soldStock);
                    String currentRedisStock = stringRedisTemplate.opsForValue().get(stockKey);
                    int currentStock = 0;
                    try { currentStock = Integer.parseInt(currentRedisStock); } catch (Exception ignored) {}
                    // 只降低不抬高：避免MQ消费延迟时覆盖Lua脚本的库存扣减
                    // Redis < remaining 说明Lua已扣减但sold_stock还没更新（MQ消费中），不处理
                    // Redis > remaining 说明库存虚高（如管理员降库存），需要降低防超卖
                    if (currentStock > remaining) {
                        stringRedisTemplate.opsForValue().set(stockKey, String.valueOf(remaining), ttlSeconds, java.util.concurrent.TimeUnit.SECONDS);
                        log.info("定时同步库存(降低)：秒杀商品{} Redis库存 {} -> {} (DB总{}-已售{})", item.getItemId(), currentStock, remaining, dbStock, soldStock);
                    }
                }
            } catch (Exception e) {
                log.error("定时自动预热：秒杀商品{}预热失败", item.getItemId(), e);
            }
        }
        if (count > 0) {
            log.info("定时自动预热：本次共预热{}个秒杀商品", count);
        }
    }

    /**
     * 8. 秒杀优惠券自动预热 - 开抢前5分钟自动写入Redis
     * 同秒杀商品逻辑，兜底防止秒杀开始前没来得及自动把预热写入redis
     * 已预热的会同步DB实际剩余可秒杀库存（seckill_stock - sold_stock）
     */
    @Scheduled(fixedDelay = 60 * 1000)
    public void autoPreheatSeckillCoupons() {
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime preheatWindow = now.plusMinutes(5);
        List<SeckillCoupon> coupons = seckillCouponMapper.selectList(
                new LambdaQueryWrapper<SeckillCoupon>()
                        .le(SeckillCoupon::getRushBeginTime, preheatWindow)
                        .gt(SeckillCoupon::getRushEndTime, now)
                        .last("LIMIT 100")
        );
        if (coupons.isEmpty()) {
            return;
        }
        int count = 0;
        for (SeckillCoupon coupon : coupons) {
            try {
                String stockKey = RedisConstants.SECKILL_COUPON_STOCK_KEY + coupon.getCouponId();
                Boolean exists = stringRedisTemplate.hasKey(stockKey);
                if (Boolean.FALSE.equals(exists)) {
                    seckillService.preheatCouponStockToRedis(coupon.getCouponId());
                    count++;
                    log.info("定时自动预热：秒杀优惠券{}已预热", coupon.getCouponId());
                } else {
                    // 已预热：同步DB实际剩余可秒杀库存 = 总库存 - 已售库存
                    long ttlSeconds = Duration.between(now, coupon.getRushEndTime()).getSeconds();
                    if (ttlSeconds <= 0) continue;
                    int dbStock = coupon.getSeckillStock() != null ? coupon.getSeckillStock() : 0;
                    int soldStock = coupon.getSoldStock() != null ? coupon.getSoldStock() : 0;
                    int remaining = Math.max(0, dbStock - soldStock);
                    String currentRedisStock = stringRedisTemplate.opsForValue().get(stockKey);
                    int currentStock = 0;
                    try { currentStock = Integer.parseInt(currentRedisStock); } catch (Exception ignored) {}
                    // 只降低不抬高：避免MQ消费延迟时覆盖Lua脚本的库存扣减
                    if (currentStock > remaining) {
                        stringRedisTemplate.opsForValue().set(stockKey, String.valueOf(remaining), ttlSeconds, java.util.concurrent.TimeUnit.SECONDS);
                        log.info("定时同步库存(降低)：秒杀优惠券{} Redis库存 {} -> {} (DB总{}-已售{})", coupon.getCouponId(), currentStock, remaining, dbStock, soldStock);
                    }
                }
            } catch (Exception e) {
                log.error("定时自动预热：秒杀优惠券{}预热失败", coupon.getCouponId(), e);
            }
        }
        if (count > 0) {
            log.info("定时自动预热：本次共预热{}张秒杀优惠券", count);
        }
    }
}
