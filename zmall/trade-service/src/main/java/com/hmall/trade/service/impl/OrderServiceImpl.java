package com.hmall.trade.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.api.vo.MerchantOrderVO;
import com.hmall.common.domain.PageDTO;
import com.hmall.api.client.ItemClient;
import com.hmall.api.client.UserClient;
import com.hmall.api.dto.*;
import com.hmall.common.config.RedisConstants;
import com.hmall.common.constants.MqConstants;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.utils.RabbitMqHelper;
import com.hmall.common.utils.UserContext;
import com.hmall.trade.domain.dto.OrderFormDTO;
import com.hmall.trade.domain.po.*;
import com.hmall.trade.mapper.CouponMapper;
import com.hmall.trade.mapper.OrderMapper;
import com.hmall.trade.mapper.SeckillCouponMapper;
import com.hmall.trade.mapper.SeckillItemMapper;
import com.hmall.trade.mapper.UserCouponMapper;
import com.hmall.trade.service.ICouponService;
import com.hmall.trade.service.IOrderDetailService;
import com.hmall.trade.service.IOrderService;
import io.seata.spring.annotation.GlobalTransactional;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class OrderServiceImpl extends ServiceImpl<OrderMapper, Order> implements IOrderService {

    private final ItemClient itemClient;
    private final UserClient userClient;
    private final IOrderDetailService detailService;
    private final RabbitMqHelper rabbitMqHelper;
    private final UserCouponMapper userCouponMapper;
    private final CouponMapper couponMapper;
    private final SeckillItemMapper seckillItemMapper;
    private final SeckillCouponMapper seckillCouponMapper;
    private final ICouponService couponService;
    private final StringRedisTemplate stringRedisTemplate;

    @Override
    @GlobalTransactional
    public Long createOrder(OrderFormDTO orderFormDTO) {
        Long userId = UserContext.getUser();

        // 1.订单数据
        Order order = new Order();
        // 1.1.查询商品
        List<OrderDetailDTO> detailDTOS = orderFormDTO.getDetails();
        // 1.2.获取商品id和数量的Map
        Map<Long, Integer> itemNumMap = detailDTOS.stream()
                .collect(Collectors.toMap(OrderDetailDTO::getItemId, OrderDetailDTO::getNum));
        Set<Long> itemIds = itemNumMap.keySet();
        // 1.3.查询商品
        List<ItemDTO> items = itemClient.queryItemByIds(itemIds);
        if (items == null || items.size() < itemIds.size()) {
            throw new BadRequestException("商品不存在");
        }
        // 1.4.基于商品价格、购买数量计算商品总价
        int total = 0;
        for (ItemDTO item : items) {
            total += item.getPrice() * itemNumMap.get(item.getId());
        }

        // 2.优惠券计算
        int discountAmount = 0;
        Long couponId = orderFormDTO.getCouponId();
        if (couponId != null) {
            discountAmount = calculateDiscount(couponId, userId, total, items, itemNumMap);
        }
        int actualFee = Math.max(0, total - discountAmount);

        order.setTotalFee(actualFee);
        order.setDiscountAmount(discountAmount);
        order.setCouponId(couponId);
        order.setPaymentType(orderFormDTO.getPaymentType());
        order.setUserId(userId);
        // 秒杀商品必须通过秒杀通道下单，不允许通过普通下单接口
        boolean hasSeckillItem = detailDTOS.stream().anyMatch(d -> {
            ItemDTO itemDTO = items.stream()
                    .filter(i -> i.getId().equals(d.getItemId()))
                    .findFirst().orElse(null);
            return itemDTO != null && itemDTO.getItemType() != null && itemDTO.getItemType() == 2;
        });
        if (hasSeckillItem) {
            throw new BadRequestException("秒杀商品请通过秒杀通道下单");
        }
        order.setOrderType(1); // 普通商品订单
        order.setStatus(1);
        // 1.6.将Order写入数据库order表中
        save(order);

        // 3.保存订单详情
        List<OrderDetail> details = buildDetails(order.getId(), items, itemNumMap);
        detailService.saveBatch(details);

        // 4.发送消息通知购物车服务清理商品
        try {
            CartClearMessageDTO message = new CartClearMessageDTO(order.getId(), userId, itemIds);
            rabbitMqHelper.sendMessageWithConfirm(MqConstants.TRADE_TOPIC_EXCHANGE, MqConstants.ORDER_CREATE_KEY, message, 3);
        } catch (Exception e) {
            log.error("发送清理购物车消息失败", e);
        }

        // 5.扣减库存
        try {
            itemClient.deductStock(detailDTOS);
        } catch (Exception e) {
            throw new BizIllegalException("库存不足！");
        }

        // 6.标记优惠券为"已下单"
        if (couponId != null) {
            markCouponOrdered(couponId, userId, order.getId());
        }

        // 7.发送延迟消息，用于超时未支付取消订单
        try {
            rabbitMqHelper.sendDelayMessageWithConfirm(
                    MqConstants.DELAY_EXCHANGE_NAME,
                    MqConstants.DELAY_ORDER_KEY,
                    order.getId(),
                    30 * 60 * 1000,
                    3);
        } catch (Exception e) {
            log.error("发送延迟消息失败", e);
        }

        return order.getId();
    }

    @Override
    public MerchantOrderVO queryOrderById(Long orderId) {
        Long userId = UserContext.getUser();
        Order order = getById(orderId);
        if (order == null || !order.getUserId().equals(userId)) {
            throw new BadRequestException("订单不存在");
        }
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        MerchantOrderVO vo = new MerchantOrderVO()
                .setId(order.getId())
                .setTotalFee(order.getTotalFee())
                .setPaymentType(order.getPaymentType())
                .setUserId(order.getUserId())
                .setStatus(order.getStatus())
                .setStatusText(getStatusText(order.getStatus()))
                .setOrderType(order.getOrderType() != null ? order.getOrderType() : 1)
                .setCreateTime(order.getCreateTime() != null ? order.getCreateTime().format(formatter) : null)
                .setPayTime(order.getPayTime() != null ? order.getPayTime().format(formatter) : null)
                .setConsignTime(order.getConsignTime() != null ? order.getConsignTime().format(formatter) : null);
        if (order.getOrderType() != null && order.getOrderType() == 2) {
            vo.setItemName("优惠券购买订单");
            vo.setItemCount(1);
        } else {
            List<OrderDetail> details = detailService.lambdaQuery()
                    .eq(OrderDetail::getOrderId, orderId).list();
            if (details != null && !details.isEmpty()) {
                vo.setItemName(details.get(0).getName());
                vo.setItemCount(details.stream().mapToInt(OrderDetail::getNum).sum());
                List<MerchantOrderVO.OrderDetailVO> detailVOList = details.stream().map(d -> {
                    MerchantOrderVO.OrderDetailVO dvo = new MerchantOrderVO.OrderDetailVO();
                    dvo.setItemId(d.getItemId());
                    dvo.setName(d.getName());
                    dvo.setPrice(d.getPrice());
                    dvo.setNum(d.getNum());
                    dvo.setImage(d.getImage());
                    dvo.setSpec(d.getSpec());
                    return dvo;
                }).collect(Collectors.toList());
                vo.setOrderDetails(detailVOList);
            }
        }
        return vo;
    }

    /**
     * 创建优惠券购买订单
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public Long createCouponOrder(Long couponId, Long userId, Integer paymentType) {
        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon == null || coupon.getPurchasePrice() == null || coupon.getPurchasePrice() <= 0) {
            throw new BadRequestException("优惠券不可购买");
        }
        // 校验优惠券状态和库存
        if (coupon.getStatus() != 1) {
            throw new BadRequestException("优惠券已下架");
        }
        if (coupon.getReceivedCount() >= coupon.getTotalCount()) {
            throw new BadRequestException("优惠券已领完");
        }
        // 校验用户是否已领取
        Long userReceived = Long.valueOf(userCouponMapper.selectCount((
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId)
                        .eq(UserCoupon::getCouponId, couponId))));
        if (userReceived != null && userReceived >= coupon.getPerUserLimit()) {
            throw new BadRequestException("已达到领取上限");
        }

        Order order = new Order();
        order.setTotalFee(coupon.getPurchasePrice());
        order.setPaymentType(paymentType);
        order.setUserId(userId);
        order.setCouponId(couponId);
        order.setDiscountAmount(0);
        order.setOrderType(2); // 优惠券购买订单
        order.setStatus(1); // 未付款
        save(order);

        // 发送30分钟超时取消消息
        try {
            rabbitMqHelper.sendDelayMessageWithConfirm(
                    MqConstants.DELAY_EXCHANGE_NAME,
                    MqConstants.DELAY_ORDER_KEY,
                    order.getId(),
                    30 * 60 * 1000,
                    3);
        } catch (Exception e) {
            log.error("发送优惠券购买延迟消息失败", e);
        }

        log.info("优惠券购买订单创建成功: orderId={}, couponId={}, userId={}", order.getId(), couponId, userId);
        return order.getId();
    }

    /**
     * 秒杀商品抢购成功后直接创建正式订单
     * 由SeckillOrderListener调用，不需要前端传OrderFormDTO
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public Long createSeckillOrder(Long orderId, Long userId, Long itemId, int num, int seckillPrice, Long couponId) {
        // 查询商品信息
        ItemDTO item = itemClient.queryItemById(itemId);
        if (item == null) {
            throw new BadRequestException("商品不存在");
        }

        // 优惠券计算
        int discountAmount = 0;
        if (couponId != null) {
            discountAmount = calculateSeckillDiscount(couponId, userId, seckillPrice * num, itemId);
        }
        int actualFee = Math.max(0, seckillPrice * num - discountAmount);

        // 创建订单（使用秒杀价）
        Order order = new Order();
        order.setId(orderId); // 使用秒杀时生成的orderId
        order.setTotalFee(actualFee);
        order.setPaymentType(3); // 默认支付方式
        order.setUserId(userId);
        order.setOrderType(3); // 秒杀商品订单
        order.setStatus(1); // 未付款
        order.setCouponId(couponId);
        order.setDiscountAmount(discountAmount);
        save(order);

        // 保存订单详情
        OrderDetail detail = new OrderDetail();
        detail.setName(item.getName());
        detail.setSpec(item.getSpec());
        detail.setPrice(seckillPrice); // 使用秒杀价
        detail.setNum(num);
        detail.setItemId(itemId);
        detail.setImage(item.getImage());
        detail.setOrderId(orderId);
        detailService.save(detail);

        // 扣减DB库存（秒杀商品也需要扣减DB库存，保持Redis与DB一致）
        try {
            List<OrderDetailDTO> deductList = Collections.singletonList(
                    new OrderDetailDTO().setItemId(itemId).setNum(num));
            itemClient.deductStock(deductList);
        } catch (Exception e) {
            throw new BizIllegalException("秒杀商品库存不足！");
        }

        // 标记优惠券为"已下单"
        if (couponId != null) {
            markCouponOrdered(couponId, userId, orderId);
        }

        // 发送延迟消息，超时未支付取消订单
        try {
            rabbitMqHelper.sendDelayMessageWithConfirm(
                    MqConstants.DELAY_EXCHANGE_NAME,
                    MqConstants.DELAY_ORDER_KEY,
                    orderId,
                    30 * 60 * 1000, // 30分钟超时
                    3);
        } catch (Exception e) {
            log.error("发送秒杀订单延迟消息失败", e);
        }

        log.info("秒杀商品订单创建成功: orderId={}, itemId={}, userId={}", orderId, itemId, userId);
        return orderId;
    }

    /**
     * 计算秒杀商品优惠券优惠金额
     */
    private int calculateSeckillDiscount(Long couponId, Long userId, int totalFee, Long itemId) {
        // 查询user_coupon记录，确认用户已领取且未使用
        UserCoupon userCoupon = userCouponMapper.selectOne(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId)
                        .eq(UserCoupon::getCouponId, couponId)
                        .eq(UserCoupon::getStatus, 1));
        if (userCoupon == null) {
            throw new BadRequestException("优惠券不可用：未领取或已使用");
        }
        // 校验有效期
        if (userCoupon.getExpireTime() != null && LocalDateTime.now().isAfter(userCoupon.getExpireTime())) {
            userCoupon.setStatus(4); // 已过期
            userCouponMapper.updateById(userCoupon);
            throw new BadRequestException("优惠券已过期");
        }
        // 查询优惠券信息
        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon == null || coupon.getStatus() != 1) {
            throw new BadRequestException("优惠券不可用");
        }
        // 校验适用范围
        if (coupon.getScopeType() != null && coupon.getScopeType() == 2) {
            List<Long> scopeItemIds = couponService.getCouponItemIds(couponId);
            if (!scopeItemIds.contains(itemId)) {
                throw new BadRequestException("优惠券不适用于当前商品");
            }
        }
        // 校验有效期范围（仅固定有效期优惠券校验，领后N天有效的已通过userCoupon.expireTime校验）
        if (coupon.getValidDays() == null && coupon.getBeginTime() != null && coupon.getEndTime() != null) {
            LocalDateTime now = LocalDateTime.now();
            if (now.isBefore(coupon.getBeginTime()) || now.isAfter(coupon.getEndTime())) {
                throw new BadRequestException("优惠券不在有效期内");
            }
        }
        // 校验门槛
        if (totalFee < coupon.getThresholdAmount()) {
            throw new BadRequestException("未达到优惠券使用门槛");
        }
        // 计算优惠金额
        if (coupon.getType() == 1) {
            return coupon.getDiscountValue();
        } else if (coupon.getType() == 2) {
            return totalFee * (100 - coupon.getDiscountValue()) / 100;
        }
        return 0;
    }

    /**
     * 计算优惠券优惠金额（增加适用范围校验）
     */
    private int calculateDiscount(Long couponId, Long userId, int totalFee, List<ItemDTO> items, Map<Long, Integer> itemNumMap) {
        // 查询user_coupon记录，确认用户已领取且未使用
        UserCoupon userCoupon = userCouponMapper.selectOne(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId)
                        .eq(UserCoupon::getCouponId, couponId)
                        .eq(UserCoupon::getStatus, 1));
        if (userCoupon == null) {
            throw new BadRequestException("优惠券不可用：未领取或已使用");
        }
        // 校验有效期
        if (userCoupon.getExpireTime() != null && LocalDateTime.now().isAfter(userCoupon.getExpireTime())) {
            userCoupon.setStatus(4); // 已过期
            userCouponMapper.updateById(userCoupon);
            throw new BadRequestException("优惠券已过期");
        }
        // 查询优惠券信息
        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon == null || coupon.getStatus() != 1) {
            throw new BadRequestException("优惠券不可用");
        }
        // 校验适用范围 & 计算适用商品金额
        int scopeTotal = totalFee; // 默认全部商品适用
        if (coupon.getScopeType() != null && coupon.getScopeType() == 2) {
            // 部分商品适用：通过coupon_item关系表查询适用商品
            List<Long> scopeItemIds = couponService.getCouponItemIds(couponId);
            Set<Long> scopeItemIdSet = new HashSet<>(scopeItemIds);
            boolean anyMatch = items.stream().anyMatch(item -> scopeItemIdSet.contains(item.getId()));
            if (!anyMatch) {
                throw new BadRequestException("优惠券不适用于当前商品");
            }
            // 只计算适用范围内商品的金额作为门槛
            scopeTotal = items.stream()
                    .filter(item -> scopeItemIdSet.contains(item.getId()))
                    .mapToInt(item -> item.getPrice() * itemNumMap.getOrDefault(item.getId(), 1))
                    .sum();
            if (scopeTotal < coupon.getThresholdAmount()) {
                throw new BadRequestException("适用商品未达到优惠券使用门槛");
            }
        } else {
            // 全部商品适用
            if (totalFee < coupon.getThresholdAmount()) {
                throw new BadRequestException("未达到优惠券使用门槛");
            }
        }
        // 校验有效期范围（仅固定有效期优惠券校验，领后N天有效的已通过userCoupon.expireTime校验）
        log.info("【优惠券有效期校验-多商品】couponId={} validDays={} beginTime={} endTime={}",
                coupon.getId(), coupon.getValidDays(), coupon.getBeginTime(), coupon.getEndTime());
        if (coupon.getValidDays() == null && coupon.getBeginTime() != null && coupon.getEndTime() != null) {
            LocalDateTime now = LocalDateTime.now();
            log.info("【优惠券有效期校验-多商品】now={} isBefore={} isAfter={}", now,
                    now.isBefore(coupon.getBeginTime()), now.isAfter(coupon.getEndTime()));
            if (now.isBefore(coupon.getBeginTime()) || now.isAfter(coupon.getEndTime())) {
                throw new BadRequestException("优惠券不在有效期内");
            }
        }
        // 计算优惠金额
        if (coupon.getType() == 1) {
            // 满减券：直接减免
            return coupon.getDiscountValue();
        } else if (coupon.getType() == 2) {
            // 折扣券：按折扣率计算，基于适用范围内商品金额
            int discount = scopeTotal * (100 - coupon.getDiscountValue()) / 100;
            return discount;
        }
        return 0;
    }

    @Override
    public void markOrderPaySuccess(Long orderId) {
        Order order = getById(orderId);
        if (order == null) {
            log.debug("订单不存在: orderId={}", orderId);
            return;
        }

        // 优惠券购买订单：支付成功后自动发货
        if (order.getOrderType() != null && order.getOrderType() == 2) {
            boolean success = lambdaUpdate()
                    .set(Order::getStatus, 4) // 直接交易成功（自动发货）
                    .set(Order::getPayTime, LocalDateTime.now())
                    .set(Order::getConsignTime, LocalDateTime.now())
                    .set(Order::getEndTime, LocalDateTime.now())
                    .eq(Order::getId, orderId)
                    .eq(Order::getStatus, 1)
                    .update();
            if (success) {
                // 自动发货：创建user_coupon
                couponService.deliverCouponOrder(orderId, order.getUserId(), order.getCouponId());
                log.info("优惠券购买订单支付成功，自动发货: orderId={}", orderId);
            }
            return;
        }

        // 秒杀商品订单：支付成功
        if (order.getOrderType() != null && order.getOrderType() == 3) {
            boolean success = lambdaUpdate()
                    .set(Order::getStatus, 2)
                    .set(Order::getPayTime, LocalDateTime.now())
                    .eq(Order::getId, orderId)
                    .eq(Order::getStatus, 1)
                    .update();
            if (success) {
                log.info("秒杀商品订单支付成功: orderId={}", orderId);
            }
            return;
        }

        // 商品订单：使用乐观锁原子更新
        boolean success = lambdaUpdate()
                .set(Order::getStatus, 2)
                .set(Order::getPayTime, LocalDateTime.now())
                .eq(Order::getId, orderId)
                .eq(Order::getStatus, 1)
                .update();
        if (!success) {
            log.debug("订单支付状态更新跳过，订单可能已处理: orderId={}", orderId);
            return;
        }

        // 支付成功后，更新优惠券状态为"已支付"
        if (order.getCouponId() != null) {
            markCouponPaid(order.getCouponId(), order.getUserId(), order.getId());
        }
    }

    private List<OrderDetail> buildDetails(Long orderId, List<ItemDTO> items, Map<Long, Integer> numMap) {
        List<OrderDetail> details = new ArrayList<>(items.size());
        for (ItemDTO item : items) {
            OrderDetail detail = new OrderDetail();
            detail.setName(item.getName());
            detail.setSpec(item.getSpec());
            detail.setPrice(item.getPrice());
            detail.setNum(numMap.get(item.getId()));
            detail.setItemId(item.getId());
            detail.setImage(item.getImage());
            detail.setOrderId(orderId);
            details.add(detail);
        }
        return details;
    }

    @Override
    public void cancelOrder(Long orderId) {
        Order order = getById(orderId);
        if (order == null) {
            return;
        }

        // 优惠券购买订单取消
        if (order.getOrderType() != null && order.getOrderType() == 2) {
            boolean success = lambdaUpdate()
                    .set(Order::getStatus, 5)
                    .set(Order::getCloseTime, LocalDateTime.now())
                    .eq(Order::getId, orderId)
                    .eq(Order::getStatus, 1)
                    .update();
            if (success) {
                // 回退秒杀券Redis库存（如果是秒杀券购买订单）
                if (order.getCouponId() != null) {
                    Coupon coupon = couponMapper.selectById(order.getCouponId());
                    if (coupon != null && coupon.getCouponType() != null && coupon.getCouponType() == 2) {
                        String stockKey = RedisConstants.SECKILL_COUPON_STOCK_KEY + order.getCouponId();
                        // 1. DB: sold_stock - 1（原子操作，先扣再读）
                        seckillCouponMapper.update(null,
                                new LambdaUpdateWrapper<SeckillCoupon>()
                                        .eq(SeckillCoupon::getCouponId, order.getCouponId())
                                        .setSql("sold_stock = GREATEST(0, sold_stock - 1)"));
                        // 2. 重新读取DB计算剩余库存并同步Redis（避免 increment 超过 seckill_stock 上限）
                        SeckillCoupon seckillCoupon = seckillCouponMapper.selectById(order.getCouponId());
                        if (seckillCoupon != null && seckillCoupon.getRushEndTime() != null
                                && seckillCoupon.getRushEndTime().isAfter(LocalDateTime.now())) {
                            int dbStock = seckillCoupon.getSeckillStock() != null ? seckillCoupon.getSeckillStock() : 0;
                            int soldStock = seckillCoupon.getSoldStock() != null ? seckillCoupon.getSoldStock() : 0;
                            int remaining = Math.max(0, dbStock - soldStock);
                            long ttl = Duration.between(LocalDateTime.now(), seckillCoupon.getRushEndTime()).getSeconds();
                            if (ttl > 0) {
                                stringRedisTemplate.opsForValue().set(stockKey, String.valueOf(remaining), ttl, TimeUnit.SECONDS);
                            }
                        }
                        // 3. 恢复用户已领数量
                        String userCountKey = RedisConstants.SECKILL_COUPON_USER_COUNT_KEY
                                + order.getCouponId() + ":" + order.getUserId();
                        stringRedisTemplate.opsForValue().decrement(userCountKey);
                        // 4. 移除订单集合中的用户
                        String orderKey = RedisConstants.SECKILL_COUPON_ORDER_KEY + order.getCouponId();
                        stringRedisTemplate.opsForSet().remove(orderKey, order.getUserId().toString());
                        log.info("秒杀券购买订单取消，已回退DB已售和Redis库存: couponId={}, userId={}",
                                order.getCouponId(), order.getUserId());
                    }
                }
                log.info("优惠券购买订单取消成功: orderId={}", orderId);
            }
            return;
        }

        // 秒杀商品订单取消
        if (order.getOrderType() != null && order.getOrderType() == 3) {
            boolean success = lambdaUpdate()
                    .set(Order::getStatus, 5)
                    .set(Order::getCloseTime, LocalDateTime.now())
                    .eq(Order::getId, orderId)
                    .eq(Order::getStatus, 1)
                    .update();
            if (success) {
                // 回退秒杀商品Redis库存
                List<OrderDetail> seckillDetails = detailService.lambdaQuery()
                        .eq(OrderDetail::getOrderId, orderId)
                        .list();
                for (OrderDetail detail : seckillDetails) {
                    String stockKey = RedisConstants.SECKILL_STOCK_KEY + detail.getItemId();
                    // 1. DB: sold_stock - 1（原子操作，先扣再读）
                    seckillItemMapper.update(null,
                            new LambdaUpdateWrapper<SeckillItem>()
                                    .eq(SeckillItem::getItemId, detail.getItemId())
                                    .setSql("sold_stock = GREATEST(0, sold_stock - 1)"));
                    // 2. 重新读取DB计算剩余库存并同步Redis（避免 increment 超过 seckill_stock 上限）
                    SeckillItem seckillItem = seckillItemMapper.selectById(detail.getItemId());
                    if (seckillItem != null && seckillItem.getRushEndTime() != null
                            && seckillItem.getRushEndTime().isAfter(LocalDateTime.now())) {
                        int dbStock = seckillItem.getSeckillStock() != null ? seckillItem.getSeckillStock() : 0;
                        int soldStock = seckillItem.getSoldStock() != null ? seckillItem.getSoldStock() : 0;
                        int remaining = Math.max(0, dbStock - soldStock);
                        long ttl = Duration.between(LocalDateTime.now(), seckillItem.getRushEndTime()).getSeconds();
                        if (ttl > 0) {
                            stringRedisTemplate.opsForValue().set(stockKey, String.valueOf(remaining), ttl, TimeUnit.SECONDS);
                        }
                    }
                    // 3. 恢复用户已购数量
                    String userCountKey = RedisConstants.SECKILL_USER_COUNT_KEY
                            + detail.getItemId() + ":" + order.getUserId();
                    stringRedisTemplate.opsForValue().decrement(userCountKey);
                    // 4. 移除订单集合中的用户
                    String orderKey = RedisConstants.SECKILL_ORDER_KEY + detail.getItemId();
                    stringRedisTemplate.opsForSet().remove(orderKey, order.getUserId().toString());
                    log.info("秒杀商品订单取消，已回退DB已售和Redis库存: itemId={}, userId={}",
                            detail.getItemId(), order.getUserId());
                }
                // 恢复DB库存
                List<OrderDetailDTO> detailDTOS = seckillDetails.stream()
                        .map(d -> new OrderDetailDTO()
                                .setItemId(d.getItemId())
                                .setNum(d.getNum()))
                        .collect(Collectors.toList());
                try {
                    itemClient.restoreStock(detailDTOS);
                } catch (Exception e) {
                    log.error("秒杀商品订单取消恢复DB库存失败，订单id：{}", orderId, e);
                }
                // 取消时恢复优惠券状态（含秒杀券Redis库存回退）
                if (order.getCouponId() != null) {
                    revertCouponToUnused(order.getCouponId(), order.getUserId(), order.getId());
                }
                log.info("秒杀商品订单取消成功: orderId={}", orderId);
            }
            return;
        }

        // 商品订单取消
        boolean success = lambdaUpdate()
                .set(Order::getStatus, 5)
                .set(Order::getCloseTime, LocalDateTime.now())
                .eq(Order::getId, orderId)
                .eq(Order::getStatus, 1)
                .update();
        if (!success) {
            log.debug("订单取消跳过，订单状态已变更: orderId={}", orderId);
            return;
        }
        // 恢复库存
        List<OrderDetail> details = detailService.lambdaQuery()
                .eq(OrderDetail::getOrderId, orderId)
                .list();
        List<OrderDetailDTO> detailDTOS = details.stream()
                .map(d -> new OrderDetailDTO()
                        .setItemId(d.getItemId())
                        .setNum(d.getNum()))
                .collect(Collectors.toList());
        try {
            itemClient.restoreStock(detailDTOS);
        } catch (Exception e) {
            log.error("恢复库存失败，订单id：{}，需人工补偿", orderId, e);
        }

        // 取消订单时，恢复优惠券状态（含秒杀券Redis库存回退）
        if (order.getCouponId() != null) {
            revertCouponToUnused(order.getCouponId(), order.getUserId(), order.getId());
        }
    }

    @Override
    public PageDTO<MerchantOrderVO> queryMerchantOrderPage(int page, int size, Integer status, String beginTime, String endTime) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();
        if (status != null) {
            wrapper.eq(Order::getStatus, status);
        }
        if (beginTime != null && !beginTime.isEmpty()) {
            wrapper.ge(Order::getCreateTime, beginTime);
        }
        if (endTime != null && !endTime.isEmpty()) {
            wrapper.le(Order::getCreateTime, endTime);
        }
        wrapper.orderByDesc(Order::getCreateTime);
        Page<Order> orderPage = page(new Page<>(page, size), wrapper);

        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        List<MerchantOrderVO> list = orderPage.getRecords().stream().map(order -> {
            MerchantOrderVO vo = new MerchantOrderVO()
                    .setId(order.getId())
                    .setTotalFee(order.getTotalFee())
                    .setPaymentType(order.getPaymentType())
                    .setUserId(order.getUserId())
                    .setStatus(order.getStatus())
                    .setStatusText(getStatusText(order.getStatus()))
                    .setOrderType(order.getOrderType() != null ? order.getOrderType() : 1)
                    .setCreateTime(order.getCreateTime() != null ? order.getCreateTime().format(formatter) : null)
                    .setPayTime(order.getPayTime() != null ? order.getPayTime().format(formatter) : null)
                    .setConsignTime(order.getConsignTime() != null ? order.getConsignTime().format(formatter) : null);
            // 优惠券购买订单特殊处理
            if (order.getOrderType() != null && order.getOrderType() == 2) {
                vo.setItemName("优惠券购买订单");
                vo.setItemCount(1);
            } else if (order.getOrderType() != null && order.getOrderType() == 3) {
                // 秒杀商品订单：显示真实商品名 + [秒杀] 前缀提示
                List<OrderDetail> details = detailService.lambdaQuery()
                        .eq(OrderDetail::getOrderId, order.getId()).list();
                if (details != null && !details.isEmpty()) {
                    vo.setItemName("[秒杀] " + details.get(0).getName());
                    vo.setItemCount(details.stream().mapToInt(OrderDetail::getNum).sum());
                } else {
                    vo.setItemName("[秒杀] 秒杀商品订单");
                    vo.setItemCount(1);
                }
            } else {
                List<OrderDetail> details = detailService.lambdaQuery()
                        .eq(OrderDetail::getOrderId, order.getId()).list();
                if (details != null && !details.isEmpty()) {
                    vo.setItemName(details.get(0).getName());
                    vo.setItemCount(details.stream().mapToInt(OrderDetail::getNum).sum());
                }
            }
            return vo;
        }).collect(Collectors.toList());
        return PageDTO.of(orderPage.getTotal(), orderPage.getPages(), list);
    }

    @Override
    public MerchantOrderVO queryMerchantOrderDetail(Long orderId) {
        Order order = getById(orderId);
        if (order == null) {
            return null;
        }
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        MerchantOrderVO vo = new MerchantOrderVO()
                .setId(order.getId())
                .setTotalFee(order.getTotalFee())
                .setPaymentType(order.getPaymentType())
                .setUserId(order.getUserId())
                .setStatus(order.getStatus())
                .setStatusText(getStatusText(order.getStatus()))
                .setOrderType(order.getOrderType() != null ? order.getOrderType() : 1)
                .setCreateTime(order.getCreateTime() != null ? order.getCreateTime().format(formatter) : null)
                .setPayTime(order.getPayTime() != null ? order.getPayTime().format(formatter) : null)
                .setConsignTime(order.getConsignTime() != null ? order.getConsignTime().format(formatter) : null);
        if (order.getOrderType() != null && order.getOrderType() == 2) {
            vo.setItemName("优惠券购买订单");
            vo.setItemCount(1);
        } else {
            List<OrderDetail> details = detailService.lambdaQuery()
                    .eq(OrderDetail::getOrderId, orderId).list();
            if (details != null && !details.isEmpty()) {
                vo.setItemName(details.get(0).getName());
                vo.setItemCount(details.stream().mapToInt(OrderDetail::getNum).sum());
                List<MerchantOrderVO.OrderDetailVO> detailVOList = details.stream().map(d -> {
                    MerchantOrderVO.OrderDetailVO dvo = new MerchantOrderVO.OrderDetailVO();
                    dvo.setItemId(d.getItemId());
                    dvo.setName(d.getName());
                    dvo.setPrice(d.getPrice());
                    dvo.setNum(d.getNum());
                    dvo.setImage(d.getImage());
                    dvo.setSpec(d.getSpec());
                    return dvo;
                }).collect(Collectors.toList());
                vo.setOrderDetails(detailVOList);
            }
        }
        return vo;
    }

    /**
     * 发货（模拟：点击发货后商品立即变成到货状态）
     */
    @Override
    public void shipOrder(Long orderId) {
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }
        // 优惠券购买订单无需发货
        if (order.getOrderType() != null && order.getOrderType() == 2) {
            throw new BizIllegalException("优惠券购买订单无需发货");
        }
        if (order.getStatus() != 2) {
            throw new BizIllegalException("订单状态不允许发货");
        }
        // 模拟发货：直接从"已付款未发货"变为"已到货待确认"
        order.setStatus(3); // 已发货（模拟场景下相当于到货）
        order.setConsignTime(LocalDateTime.now());
        updateById(order);
        log.info("订单发货成功（模拟到货）: orderId={}", orderId);
    }

    /**
     * 退款（商家后台操作，商品订单和优惠券订单通用）
     */
    @Override
    public void refundOrder(Long orderId) {
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }

        // 优惠券购买订单退款：自动退，删除user_coupon
        if (order.getOrderType() != null && order.getOrderType() == 2) {
            if (order.getStatus() != 4) {
                throw new BizIllegalException("优惠券订单状态不允许退款");
            }
            order.setStatus(5);
            order.setCloseTime(LocalDateTime.now());
            updateById(order);
            // 自动退款：删除user_coupon
            couponService.refundCouponOrder(orderId, order.getUserId(), order.getCouponId());
            log.info("优惠券购买订单退款成功: orderId={}", orderId);
            return;
        }

        // 秒杀商品订单退款：回退Redis库存
        if (order.getOrderType() != null && order.getOrderType() == 3) {
            if (order.getStatus() != 2 && order.getStatus() != 3 && order.getStatus() != 4) {
                throw new BizIllegalException("订单状态不允许退款");
            }
            order.setStatus(5);
            order.setCloseTime(LocalDateTime.now());
            updateById(order);
            // 回退秒杀商品Redis库存
            List<OrderDetail> seckillDetails = detailService.lambdaQuery()
                    .eq(OrderDetail::getOrderId, orderId).list();
            for (OrderDetail detail : seckillDetails) {
                String stockKey = RedisConstants.SECKILL_STOCK_KEY + detail.getItemId();
                stringRedisTemplate.opsForValue().increment(stockKey);
                // 恢复用户已购数量
                String userCountKey = RedisConstants.SECKILL_USER_COUNT_KEY
                        + detail.getItemId() + ":" + order.getUserId();
                stringRedisTemplate.opsForValue().decrement(userCountKey);
                // 移除订单集合中的用户
                String orderKey = RedisConstants.SECKILL_ORDER_KEY + detail.getItemId();
                stringRedisTemplate.opsForSet().remove(orderKey, order.getUserId().toString());
                log.info("秒杀商品订单退款，已回退Redis库存: itemId={}, userId={}",
                        detail.getItemId(), order.getUserId());
            }
            // 恢复DB库存
            List<OrderDetailDTO> detailDTOS = seckillDetails.stream()
                    .map(d -> new OrderDetailDTO()
                            .setItemId(d.getItemId())
                            .setNum(d.getNum()))
                    .collect(Collectors.toList());
            try {
                itemClient.restoreStock(detailDTOS);
            } catch (Exception e) {
                log.error("秒杀商品订单退款恢复DB库存失败，订单id：{}", orderId, e);
            }
            // 退款时恢复优惠券状态（含秒杀券Redis库存回退）
            if (order.getCouponId() != null) {
                revertCouponToUnused(order.getCouponId(), order.getUserId(), order.getId());
            }
            log.info("秒杀商品订单退款成功: orderId={}", orderId);
            return;
        }

        // 商品订单退款
        if (order.getStatus() != 2 && order.getStatus() != 3 && order.getStatus() != 4) {
            throw new BizIllegalException("订单状态不允许退款");
        }
        order.setStatus(5);
        order.setCloseTime(LocalDateTime.now());
        updateById(order);
        List<OrderDetail> details = detailService.lambdaQuery()
                .eq(OrderDetail::getOrderId, orderId).list();
        List<OrderDetailDTO> detailDTOS = details.stream()
                .map(d -> new OrderDetailDTO()
                        .setItemId(d.getItemId())
                        .setNum(d.getNum()))
                .collect(Collectors.toList());
        try {
            itemClient.restoreStock(detailDTOS);
        } catch (Exception e) {
            log.error("退款恢复库存失败，订单id：{}", orderId, e);
        }
        // 退款时恢复优惠券状态（含秒杀券Redis库存回退）
        if (order.getCouponId() != null) {
            revertCouponToUnused(order.getCouponId(), order.getUserId(), order.getId());
        }
        log.info("商品订单退款成功: orderId={}", orderId);
    }

    @Override
    public OrderStatsDTO getMerchantOrderStats() {
        LocalDateTime todayStart = LocalDateTime.of(LocalDate.now(), LocalTime.MIN);
        LocalDateTime todayEnd = LocalDateTime.of(LocalDate.now(), LocalTime.MAX);

        OrderStatsDTO stats = new OrderStatsDTO();
        stats.setTodayNew(Long.valueOf(lambdaQuery()
                .ge(Order::getCreateTime, todayStart)
                .le(Order::getCreateTime, todayEnd)
                .count()));
        stats.setPendingShip(Long.valueOf(lambdaQuery().eq(Order::getStatus, 2).eq(Order::getOrderType, 1).count()));
        stats.setShipped(Long.valueOf(lambdaQuery().eq(Order::getStatus, 3).eq(Order::getOrderType, 1).count()));
        stats.setRefunding(Long.valueOf(lambdaQuery().eq(Order::getStatus, 7).count()));
        List<Order> todayOrders = lambdaQuery()
                .ge(Order::getCreateTime, todayStart)
                .le(Order::getCreateTime, todayEnd)
                .ne(Order::getStatus, 5)
                .list();
        stats.setTodaySales(todayOrders.stream()
                .mapToLong(o -> o.getTotalFee() != null ? o.getTotalFee() : 0).sum());
        return stats;
    }

    @Override
    public List<SalesTrendDTO> getSalesTrend(Integer days) {
        List<SalesTrendDTO> result = new ArrayList<>();
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd");
        for (int i = days - 1; i >= 0; i--) {
            LocalDate date = LocalDate.now().minusDays(i);
            LocalDateTime dayStart = LocalDateTime.of(date, LocalTime.MIN);
            LocalDateTime dayEnd = LocalDateTime.of(date, LocalTime.MAX);

            SalesTrendDTO dto = new SalesTrendDTO();
            dto.setDate(date.format(formatter));
            dto.setOrders(Long.valueOf(lambdaQuery()
                    .ge(Order::getCreateTime, dayStart)
                    .le(Order::getCreateTime, dayEnd)
                    .ne(Order::getStatus, 5)
                    .count()));
            List<Order> dayOrders = lambdaQuery()
                    .ge(Order::getCreateTime, dayStart)
                    .le(Order::getCreateTime, dayEnd)
                    .ne(Order::getStatus, 5)
                    .list();
            dto.setSales(dayOrders.stream()
                    .mapToLong(o -> o.getTotalFee() != null ? o.getTotalFee() : 0).sum());
            result.add(dto);
        }
        return result;
    }

    @Override
    public List<TopItemDTO> getTopItems(Integer limit) {
        List<OrderDetail> all = detailService.lambdaQuery()
                .apply("1=1").list();
        Map<Long, TopItemDTO> map = new HashMap<>();
        for (OrderDetail od : all) {
            TopItemDTO dto = map.computeIfAbsent(od.getItemId(), k -> {
                TopItemDTO t = new TopItemDTO();
                t.setItemId(k);
                t.setName(od.getName());
                t.setImage(od.getImage());
                t.setSold(0);
                t.setTotalSales(0L);
                return t;
            });
            dto.setSold(dto.getSold() + od.getNum());
            dto.setTotalSales(dto.getTotalSales() + (long) od.getPrice() * od.getNum());
        }
        return map.values().stream()
                .sorted((a, b) -> b.getSold().compareTo(a.getSold()))
                .limit(limit)
                .collect(Collectors.toList());
    }

    private String getStatusText(Integer status) {
        if (status == null) return "未知";
        switch (status) {
            case 1: return "待付款";
            case 2: return "待发货";
            case 3: return "已到货";
            case 4: return "交易成功";
            case 5: return "已关闭";
            case 6: return "已评价";
            case 7: return "退货审核中";
            case 8: return "退货被拒绝";
            default: return "未知";
        }
    }

    // ===== 优惠券状态管理 =====

    private void markCouponOrdered(Long couponId, Long userId, Long orderId) {
        UserCoupon userCoupon = userCouponMapper.selectOne(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId)
                        .eq(UserCoupon::getCouponId, couponId)
                        .eq(UserCoupon::getStatus, 1));
        if (userCoupon != null) {
            userCoupon.setStatus(2); // 已下单
            userCoupon.setOrderId(orderId);
            userCouponMapper.updateById(userCoupon);
        }
    }

    private void markCouponPaid(Long couponId, Long userId, Long orderId) {
        LambdaQueryWrapper<UserCoupon> wrapper = new LambdaQueryWrapper<UserCoupon>()
                .eq(UserCoupon::getUserId, userId)
                .eq(UserCoupon::getCouponId, couponId)
                .eq(UserCoupon::getStatus, 2);
        if (orderId != null) {
            wrapper.eq(UserCoupon::getOrderId, orderId);
        }
        UserCoupon userCoupon = userCouponMapper.selectOne(wrapper);
        if (userCoupon != null) {
            userCoupon.setStatus(3); // 已支付
            userCoupon.setUseTime(LocalDateTime.now());
            userCouponMapper.updateById(userCoupon);
            // 更新优惠券已使用数量
            Coupon coupon = couponMapper.selectById(couponId);
            if (coupon != null) {
                coupon.setUsedCount(coupon.getUsedCount() + 1);
                couponMapper.updateById(coupon);
            }
        }
    }

    private void revertCouponToUnused(Long couponId, Long userId, Long orderId) {
        LambdaQueryWrapper<UserCoupon> wrapper = new LambdaQueryWrapper<UserCoupon>()
                .eq(UserCoupon::getUserId, userId)
                .eq(UserCoupon::getCouponId, couponId)
                .in(UserCoupon::getStatus, 2, 3);
        if (orderId != null) {
            wrapper.eq(UserCoupon::getOrderId, orderId);
        }
        UserCoupon userCoupon = userCouponMapper.selectOne(wrapper);
        if (userCoupon != null) {
            userCoupon.setStatus(1); // 未使用
            userCoupon.setOrderId(null);
            userCoupon.setUseTime(null);
            userCouponMapper.updateById(userCoupon);
        }
        // 如果是秒杀券，回退Redis库存
        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon != null && coupon.getCouponType() != null && coupon.getCouponType() == 2) {
            revertSeckillCouponRedisStock(couponId, userId);
        }
    }

    /**
     * 回退秒杀券Redis库存
     * 注意：秒杀券在这里只回退Redis的userCount和orderSet，不回退stockKey
     * 因为秒杀券的stockKey回退已在 cancelOrder 的 orderType=2 分支中通过 sold_stock 重新计算处理
     * 此方法仅在秒杀商品订单（orderType=3）取消时调用，用于回退其关联的秒杀券
     */
    private void revertSeckillCouponRedisStock(Long couponId, Long userId) {
        // 1. DB: sold_stock - 1（原子操作）
        seckillCouponMapper.update(null,
                new LambdaUpdateWrapper<SeckillCoupon>()
                        .eq(SeckillCoupon::getCouponId, couponId)
                        .setSql("sold_stock = GREATEST(0, sold_stock - 1)"));
        // 2. 重新读取DB计算剩余库存并同步Redis
        SeckillCoupon seckillCoupon = seckillCouponMapper.selectById(couponId);
        if (seckillCoupon != null && seckillCoupon.getRushEndTime() != null
                && seckillCoupon.getRushEndTime().isAfter(LocalDateTime.now())) {
            int dbStock = seckillCoupon.getSeckillStock() != null ? seckillCoupon.getSeckillStock() : 0;
            int soldStock = seckillCoupon.getSoldStock() != null ? seckillCoupon.getSoldStock() : 0;
            int remaining = Math.max(0, dbStock - soldStock);
            long ttl = Duration.between(LocalDateTime.now(), seckillCoupon.getRushEndTime()).getSeconds();
            if (ttl > 0) {
                String stockKey = RedisConstants.SECKILL_COUPON_STOCK_KEY + couponId;
                stringRedisTemplate.opsForValue().set(stockKey, String.valueOf(remaining), ttl, TimeUnit.SECONDS);
            }
        }
        // 3. 恢复用户已领数量
        String userCountKey = RedisConstants.SECKILL_COUPON_USER_COUNT_KEY + couponId + ":" + userId;
        stringRedisTemplate.opsForValue().decrement(userCountKey);
        // 4. 移除订单集合中的用户
        String orderKey = RedisConstants.SECKILL_COUPON_ORDER_KEY + couponId;
        stringRedisTemplate.opsForSet().remove(orderKey, userId.toString());
        log.info("回退秒杀券Redis库存: couponId={}, userId={}", couponId, userId);
    }

    /**
     * 自动关闭超时未支付的订单（创建时间超过30分钟且状态仍为待付款）
     */
    private void closeTimeoutOrders(Long userId) {
        LocalDateTime timeout = LocalDateTime.now().minusMinutes(30);
        List<Order> timeoutOrders = lambdaQuery()
                .eq(Order::getUserId, userId)
                .eq(Order::getStatus, 1)
                .lt(Order::getCreateTime, timeout)
                .list();
        for (Order order : timeoutOrders) {
            cancelOrder(order.getId());
            log.info("自动关闭超时订单: orderId={}", order.getId());
        }
    }

    /**
     * 用户申请退款（待发货状态，直接退款成功）
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public void applyRefund(Long orderId) {
        Long userId = UserContext.getUser();
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }
        if (!order.getUserId().equals(userId)) {
            throw new BizIllegalException("无权操作此订单");
        }
        if (order.getStatus() != 2) {
            throw new BizIllegalException("只有待发货订单可以申请退款");
        }
        // 待发货退款直接成功
        order.setStatus(5);
        order.setCloseTime(LocalDateTime.now());
        updateById(order);
        // 退回余额
        refundBalance(order);
        // 恢复库存
        restoreStock(order);
        // 恢复优惠券
        if (order.getCouponId() != null) {
            revertCouponToUnused(order.getCouponId(), order.getUserId(), order.getId());
        }
        log.info("用户申请退款成功（待发货直接退款）: orderId={}", orderId);
    }

    /**
     * 用户申请退货（已到货状态，需要商家审核）
     */
    @Override
    public void applyReturn(Long orderId) {
        Long userId = UserContext.getUser();
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }
        if (!order.getUserId().equals(userId)) {
            throw new BizIllegalException("无权操作此订单");
        }
        if (order.getStatus() != 3 && order.getStatus() != 8) {
            throw new BizIllegalException("只有已到货或退货被拒绝的订单可以申请退货");
        }
        order.setStatus(7); // 退货审核中
        updateById(order);
        log.info("用户申请退货，等待商家审核: orderId={}", orderId);
    }

    /**
     * 用户取消退货（审核前可取消）
     */
    @Override
    public void cancelReturn(Long orderId) {
        Long userId = UserContext.getUser();
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }
        if (!order.getUserId().equals(userId)) {
            throw new BizIllegalException("无权操作此订单");
        }
        if (order.getStatus() != 7) {
            throw new BizIllegalException("只有退货审核中的订单可以取消退货");
        }
        order.setStatus(3); // 恢复为已到货
        updateById(order);
        log.info("用户取消退货，订单恢复为已到货: orderId={}", orderId);
    }

    /**
     * 商家审核通过退货
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public void approveReturn(Long orderId) {
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }
        if (order.getStatus() != 7) {
            throw new BizIllegalException("订单状态不允许审核退货");
        }
        order.setStatus(5);
        order.setCloseTime(LocalDateTime.now());
        updateById(order);
        // 退回余额
        refundBalance(order);
        // 恢复库存
        restoreStock(order);
        // 恢复优惠券
        if (order.getCouponId() != null) {
            revertCouponToUnused(order.getCouponId(), order.getUserId(), order.getId());
        }
        log.info("商家审核退货通过: orderId={}", orderId);
    }

    /**
     * 商家拒绝退货
     */
    @Override
    public void rejectReturn(Long orderId) {
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }
        if (order.getStatus() != 7) {
            throw new BizIllegalException("订单状态不允许审核退货");
        }
        order.setStatus(8); // 退货被拒绝，用户可再次申请
        updateById(order);
        log.info("商家拒绝退货，订单状态变为退货被拒绝: orderId={}", orderId);
    }

    /**
     * 用户确认收货
     */
    @Override
    public void confirmReceive(Long orderId) {
        Long userId = UserContext.getUser();
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }
        if (!order.getUserId().equals(userId)) {
            throw new BizIllegalException("无权操作此订单");
        }
        if (order.getStatus() != 3 && order.getStatus() != 8) {
            throw new BizIllegalException("只有已到货或退货被拒绝的订单可以确认收货");
        }
        order.setStatus(4); // 交易成功
        order.setEndTime(LocalDateTime.now());
        updateById(order);
        log.info("用户确认收货: orderId={}", orderId);
    }

    /**
     * 用户评价订单后更新状态为已评价
     */
    @Override
    public void commentOrder(Long orderId) {
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }
        if (order.getStatus() != 4) {
            throw new BizIllegalException("只有交易成功的订单可以评价");
        }
        order.setStatus(6); // 已评价
        order.setCommentTime(LocalDateTime.now());
        updateById(order);
        log.info("订单评价成功: orderId={}", orderId);
    }

    /**
     * 退回余额（通用方法）
     */
    private void refundBalance(Order order) {
        if (order.getTotalFee() != null && order.getTotalFee() > 0) {
            try {
                userClient.refundMoney(order.getUserId(), order.getTotalFee());
                log.info("退款到余额成功: userId={}, amount={}", order.getUserId(), order.getTotalFee());
            } catch (Exception e) {
                log.error("退款到余额失败，订单id：{}", order.getId(), e);
            }
        }
    }

    /**
     * 恢复库存（通用方法）
     */
    private void restoreStock(Order order) {
        List<OrderDetail> details = detailService.lambdaQuery()
                .eq(OrderDetail::getOrderId, order.getId()).list();
        if (!details.isEmpty()) {
            List<OrderDetailDTO> detailDTOS = details.stream()
                    .map(d -> new OrderDetailDTO()
                            .setItemId(d.getItemId())
                            .setNum(d.getNum()))
                    .collect(Collectors.toList());
            try {
                itemClient.restoreStock(detailDTOS);
            } catch (Exception e) {
                log.error("恢复库存失败，订单id：{}", order.getId(), e);
            }
        }
    }

    @Override
    public PageDTO<MerchantOrderVO> queryUserOrderPage(Long userId, int page, int size, Integer status) {
        // 自动关闭超时未支付的订单（创建时间超过30分钟且状态仍为待付款）
        closeTimeoutOrders(userId);

        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Order::getUserId, userId);
        if (status != null) {
            wrapper.eq(Order::getStatus, status);
        }
        wrapper.orderByDesc(Order::getCreateTime);
        Page<Order> orderPage = page(new Page<>(page, size), wrapper);

        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        List<MerchantOrderVO> list = orderPage.getRecords().stream().map(order -> {
            MerchantOrderVO vo = new MerchantOrderVO()
                    .setId(order.getId())
                    .setTotalFee(order.getTotalFee())
                    .setPaymentType(order.getPaymentType())
                    .setUserId(order.getUserId())
                    .setStatus(order.getStatus())
                    .setStatusText(getStatusText(order.getStatus()))
                    .setOrderType(order.getOrderType() != null ? order.getOrderType() : 1)
                    .setCreateTime(order.getCreateTime() != null ? order.getCreateTime().format(formatter) : null)
                    .setPayTime(order.getPayTime() != null ? order.getPayTime().format(formatter) : null)
                    .setConsignTime(order.getConsignTime() != null ? order.getConsignTime().format(formatter) : null);
            if (order.getOrderType() != null && order.getOrderType() == 2) {
                vo.setItemName("优惠券购买订单");
                vo.setItemCount(1);
            } else if (order.getOrderType() != null && order.getOrderType() == 3) {
                // 秒杀商品订单：显示真实商品名 + [秒杀] 前缀提示
                List<OrderDetail> details = detailService.lambdaQuery()
                        .eq(OrderDetail::getOrderId, order.getId()).list();
                if (details != null && !details.isEmpty()) {
                    vo.setItemName("[秒杀] " + details.get(0).getName());
                    vo.setItemCount(details.stream().mapToInt(OrderDetail::getNum).sum());
                } else {
                    vo.setItemName("[秒杀] 秒杀商品订单");
                    vo.setItemCount(1);
                }
            } else {
                List<OrderDetail> details = detailService.lambdaQuery()
                        .eq(OrderDetail::getOrderId, order.getId()).list();
                if (details != null && !details.isEmpty()) {
                    vo.setItemName(details.get(0).getName());
                    vo.setItemCount(details.stream().mapToInt(OrderDetail::getNum).sum());
                }
            }
            return vo;
        }).collect(Collectors.toList());
        return PageDTO.of(orderPage.getTotal(), orderPage.getPages(), list);
    }
}
