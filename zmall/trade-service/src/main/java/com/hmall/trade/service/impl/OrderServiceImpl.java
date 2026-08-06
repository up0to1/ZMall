package com.hmall.trade.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import cn.hutool.json.JSONUtil;
import com.hmall.api.vo.MerchantOrderVO;
import com.hmall.common.domain.PageDTO;
import com.hmall.api.client.ItemClient;
import com.hmall.api.client.UserClient;
import com.hmall.api.dto.*;
import com.hmall.common.config.RedisConstants;
import com.hmall.common.constants.MqConstants;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.utils.CollUtils;
import com.hmall.common.utils.RabbitMqHelper;
import com.hmall.common.utils.UserContext;
import com.hmall.trade.domain.dto.OrderFormDTO;
import com.hmall.trade.domain.dto.ShipOrderDTO;
import com.hmall.trade.domain.po.*;
import com.hmall.trade.mapper.CouponMapper;
import com.hmall.trade.mapper.OrderMapper;
import com.hmall.trade.mapper.SeckillCouponMapper;
import com.hmall.trade.mapper.SeckillItemMapper;
import com.hmall.trade.mapper.UserCouponMapper;
import com.hmall.trade.service.ICouponService;
import com.hmall.trade.service.IOrderDetailService;
import com.hmall.trade.service.IOrderLogisticsService;
import com.hmall.trade.service.IOrderService;
import io.seata.spring.annotation.GlobalTransactional;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

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
    private final IOrderLogisticsService orderLogisticsService;
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
        // 查询收货地址（一次查询，运费计算和物流记录共用）
        com.hmall.api.dto.AddressDTO addressDTO = null;
        if (orderFormDTO.getAddressId() != null) {
            try {
                addressDTO = userClient.findAddressById(orderFormDTO.getAddressId());
            } catch (Exception e) {
                log.warn("查询收货地址失败: addressId={}", orderFormDTO.getAddressId(), e);
            }
        }
        // 计算运费：根据收货地址和商品重量估算（国内默认 800 分=8元，跨境 5000 分=50元）
        int postFee = calculateShippingFee(addressDTO, items, itemNumMap);
        order.setPostFee(postFee);
        // 1.6.将Order写入数据库order表中
        save(order);

        // 2.5.保存物流记录（含收货地址、发货地、运费）
        saveOrderLogistics(order.getId(), addressDTO, postFee, items, itemNumMap);

        // 3.保存订单详情
        List<OrderDetail> details = buildDetails(order.getId(), items, itemNumMap, detailDTOS);
        detailService.saveBatch(details);

        // P1-6 修复：ORDER_PLACE 用户行为事件原在事务内发送，若后续 deductStock 失败回滚，
        // MQ 消息已发无法回滚。现移到 deductStock 之后，并通过 afterCommit 回调发送。
        // 详见下方 5.1 节。

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

        // 5.1 发送 ORDER_PLACE 用户行为事件到 user.behavior.exchange（Phase 2.5 个性化推荐画像）
        // P1-6 修复：优先注册 afterCommit 回调，事务提交后才发 MQ，避免事务回滚后 MQ 已发无法回滚。
        // 若无 Spring 事务上下文（@GlobalTransactional 场景，createOrder 未标注 @Transactional），
        // 降级为扣减库存后直接发送（保持原行为，但移到 deductStock 之后避免回滚后仍发 MQ）。
        // 注意：afterCommit 回调无法访问事务上下文，需提前捕获 userId、details、items（effectively final）。
        registerOrderPlaceBehavior(userId, details, items);

        // 6.标记优惠券为"已下单"
        if (couponId != null) {
            markCouponOrdered(couponId, userId, order.getId());
        }

        // 6.5 AI 随心搭联动：下单成功后标记搭配记录为"已下单"（accepted=1+action=order+orderId）
        // 仅立即下单流程携带 outfit 上下文；失败不阻塞下单主流程（搭配状态可后续对账）
        String outfitTaskId = orderFormDTO.getOutfitTaskId();
        if (orderFormDTO.getOutfitRecordId() != null || (outfitTaskId != null && !outfitTaskId.isEmpty())) {
            try {
                itemClient.markOutfitOrdered(orderFormDTO.getOutfitRecordId(),
                        outfitTaskId, orderFormDTO.getOutfitIndex(),
                        order.getId(), userId);
                log.info("搭配记录已下单标记已回调: orderId={}, outfitRecordId={}, outfitTaskId={}, outfitIndex={}",
                        order.getId(), orderFormDTO.getOutfitRecordId(), outfitTaskId, orderFormDTO.getOutfitIndex());
            } catch (Exception e) {
                log.warn("标记搭配记录已下单失败（不影响下单）: orderId={}, err={}", order.getId(), e.getMessage());
            }
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

    /**
     * 发送 ORDER_PLACE 用户行为事件（P1-6 修复）
     * <p>优先注册 afterCommit 回调，事务提交后才发 MQ，避免事务回滚后 MQ 已发无法回滚。
     * 若无 Spring 事务上下文（@GlobalTransactional 场景，createOrder 未标注 @Transactional），
     * 降级为直接发送（保持原行为，但已移到 deductStock 之后避免回滚后仍发 MQ）。
     *
     * @param userId  下单用户 ID（effectively final，供 afterCommit 回调捕获）
     * @param details 订单详情列表（effectively final）
     * @param items   商品 DTO 列表（effectively final）
     */
    private void registerOrderPlaceBehavior(Long userId, List<OrderDetail> details, List<ItemDTO> items) {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    doSendOrderPlaceBehavior(userId, details, items);
                }
            });
        } else {
            // 无 Spring 事务上下文（@GlobalTransactional 场景）：降级为直接发送
            doSendOrderPlaceBehavior(userId, details, items);
        }
    }

    /**
     * 实际发送 ORDER_PLACE 用户行为事件
     * <p>对每个订单详情商品发送一个事件；ItemDTO 无 shopId 字段，使用 creater（商家ID）作为 shopId。
     * <p>查询用户性别失败时 userGender 传 null 兜底（P1-8）；单条消息发送失败不阻塞其他商品埋点。
     */
    private void doSendOrderPlaceBehavior(Long userId, List<OrderDetail> details, List<ItemDTO> items) {
        Map<Long, ItemDTO> itemMap = new HashMap<>();
        for (ItemDTO i : items) {
            itemMap.put(i.getId(), i);
        }
        // 查询用户性别（失败时 userGender 传 null 兜底，P1-8；下单场景只查一次，复用到所有商品消息）
        String userGender = null;
        try {
            userGender = userClient.queryUserGender(userId);
        } catch (Exception ex) {
            log.warn("查询用户性别失败，userGender 传 null 兜底: userId={}", userId, ex);
        }
        for (OrderDetail detail : details) {
            try {
                ItemDTO itemDTO = itemMap.get(detail.getItemId());
                List<String> styleTags = null;
                if (itemDTO != null && itemDTO.getStyleTags() != null) {
                    try {
                        styleTags = JSONUtil.parseArray(itemDTO.getStyleTags()).toList(String.class);
                    } catch (Exception ignore) {
                        styleTags = null;
                    }
                }
                UserBehaviorMessage msg = new UserBehaviorMessage(
                        userId,
                        detail.getItemId(),
                        itemDTO != null ? itemDTO.getCreater() : null,
                        itemDTO != null ? itemDTO.getCategory() : null,
                        itemDTO != null ? itemDTO.getName() : null,
                        itemDTO != null ? itemDTO.getColor() : null,
                        itemDTO != null ? itemDTO.getSeason() : null,
                        itemDTO != null && itemDTO.getPrice() != null ? itemDTO.getPrice().doubleValue() : null,
                        MqConstants.BEHAVIOR_TYPE_ORDER_PLACE,
                        LocalDateTime.now().toString(),
                        itemDTO != null ? itemDTO.getImage() : null,
                        styleTags,
                        itemDTO != null ? itemDTO.getTargetGender() : null,
                        userGender
                );
                rabbitMqHelper.sendMessage(
                        MqConstants.USER_BEHAVIOR_EXCHANGE,
                        MqConstants.USER_BEHAVIOR_KEY_PREFIX + MqConstants.BEHAVIOR_TYPE_ORDER_PLACE,
                        msg
                );
                log.info("已发送用户行为事件: type={}, userId={}, itemId={}",
                        MqConstants.BEHAVIOR_TYPE_ORDER_PLACE, userId, detail.getItemId());
            } catch (Exception e) {
                log.error("发送 ORDER_PLACE 用户行为事件失败: itemId={}", detail.getItemId(), e);
            }
        }
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
                    dvo.setSkuId(d.getSkuId());
                    dvo.setName(d.getName());
                    dvo.setPrice(d.getPrice());
                    dvo.setNum(d.getNum());
                    dvo.setImage(d.getImage());
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
        detail.setPrice(seckillPrice); // 使用秒杀价
        detail.setNum(num);
        detail.setItemId(itemId);
        detail.setImage(item.getImage());
        detail.setOrderId(orderId);
        // 成本价快照（与普通订单一致，用于利润统计）
        detail.setCostPrice(item.getCostPrice() != null ? item.getCostPrice() : 0);
        // 商家ID快照：下单时从 item.creater 拷贝，商品物理删除后仍能按商家查询订单
        detail.setMerchantId(item.getCreater());
        detailService.save(detail);

        // 秒杀订单同样创建物流记录（运费默认 0，发货时商家可补填）
        saveOrderLogistics(orderId, null, 0, Collections.singletonList(item),
                Collections.singletonMap(itemId, num));

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

    private List<OrderDetail> buildDetails(Long orderId, List<ItemDTO> items, Map<Long, Integer> numMap,
                                           List<OrderDetailDTO> detailDTOS) {
        // 按 itemId 索引 skuId（同一 item 多 sku 的场景当前架构暂未支持，取第一条匹配）
        Map<Long, Long> itemSkuMap = new java.util.HashMap<>();
        if (detailDTOS != null) {
            for (OrderDetailDTO d : detailDTOS) {
                if (d.getItemId() != null && d.getSkuId() != null) {
                    itemSkuMap.putIfAbsent(d.getItemId(), d.getSkuId());
                }
            }
        }
        List<OrderDetail> details = new ArrayList<>(items.size());
        for (ItemDTO item : items) {
            OrderDetail detail = new OrderDetail();
            detail.setName(item.getName());
            detail.setPrice(item.getPrice());
            // 成本价快照：下单时从 item 表拷贝，保证历史利润统计准确
            detail.setCostPrice(item.getCostPrice() != null ? item.getCostPrice() : 0);
            detail.setNum(numMap.get(item.getId()));
            detail.setItemId(item.getId());
            // 透传 skuId（前端下单时传入，用于多 SKU 商品的具体规格记录）
            detail.setSkuId(itemSkuMap.get(item.getId()));
            detail.setImage(item.getImage());
            // 商家ID快照：下单时从 item.creater 拷贝，商品物理删除后仍能按商家查询订单
            detail.setMerchantId(item.getCreater());
            detail.setOrderId(orderId);
            details.add(detail);
        }
        return details;
    }

    /**
     * 计算运费（单位：分）
     * <p>简化规则：首重1kg内 800分（8元），每增加1kg加 200分（2元）；跨境统一 5000分（50元）
     * <p>地址为 null 时默认 800 分
     */
    private int calculateShippingFee(com.hmall.api.dto.AddressDTO addr, List<ItemDTO> items, Map<Long, Integer> numMap) {
        if (addr == null) {
            return 800; // 默认运费 8 元
        }
        // 计算总重量（克）
        int totalWeight = 0;
        for (ItemDTO item : items) {
            int w = item.getWeight() != null ? item.getWeight() : 0;
            totalWeight += w * numMap.getOrDefault(item.getId(), 1);
        }
        // 国内运费：首重1kg 8元，续重每1kg 2元；跨境运费：50元
        // 简化：地址含"海外"/"国际"字样视为跨境，否则国内
        boolean isOverseas = addr.getProvince() != null && (addr.getProvince().contains("海外") || addr.getProvince().contains("国际"));
        if (isOverseas) {
            return 5000;
        }
        int baseFee = 800; // 首重 8 元
        if (totalWeight > 1000) {
            int extraKg = (int) Math.ceil((totalWeight - 1000) / 1000.0);
            baseFee += extraKg * 200;
        }
        return baseFee;
    }

    /**
     * 保存物流记录（含收货地址快照、运费、包裹重量）
     * <p>注意：order_logistics 表的 contact/mobile/province/city/town/street 为 NOT NULL，
     * 地址查不到时填充空字符串占位，避免 SQL 约束异常。
     */
    private void saveOrderLogistics(Long orderId, com.hmall.api.dto.AddressDTO addr, int shippingFee,
                                     List<ItemDTO> items, Map<Long, Integer> numMap) {
        OrderLogistics logistics = new OrderLogistics();
        logistics.setOrderId(orderId);
        logistics.setLogisticsType(1); // 默认国内快递
        logistics.setShippingFee(shippingFee);
        logistics.setLogisticsNumber("");
        logistics.setLogisticsCompany("");

        // 填充收货地址快照（NOT NULL 字段必须有值，地址缺失时用空串占位）
        if (addr != null) {
            logistics.setContact(addr.getContact() != null ? addr.getContact() : "");
            logistics.setMobile(addr.getMobile() != null ? addr.getMobile() : "");
            logistics.setProvince(addr.getProvince() != null ? addr.getProvince() : "");
            logistics.setCity(addr.getCity() != null ? addr.getCity() : "");
            logistics.setTown(addr.getTown() != null ? addr.getTown() : "");
            logistics.setStreet(addr.getStreet() != null ? addr.getStreet() : "");
        } else {
            // 地址为空时填充占位值，避免 NOT NULL 约束异常
            logistics.setContact("");
            logistics.setMobile("");
            logistics.setProvince("");
            logistics.setCity("");
            logistics.setTown("");
            logistics.setStreet("");
        }

        // 计算包裹总重量
        int totalWeight = 0;
        for (ItemDTO item : items) {
            int w = item.getWeight() != null ? item.getWeight() : 0;
            totalWeight += w * numMap.getOrDefault(item.getId(), 1);
        }
        logistics.setWeight(totalWeight);

        orderLogisticsService.save(logistics);
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
        // AI 随心搭联动：回退搭配记录"已下单"状态（恢复下单前状态，失败不阻塞取消主流程）
        try {
            itemClient.revertOutfitOrder(orderId, order.getUserId());
            log.info("搭配记录已下单状态回退已回调: orderId={}", orderId);
        } catch (Exception e) {
            log.warn("回退搭配记录已下单状态失败（不影响取消）: orderId={}, err={}", orderId, e.getMessage());
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

    /**
     * 商家订单所有权校验
     * <p>商品订单（orderType=1或3）：订单详情中必须包含当前商家的商品。
     * <p>优惠券购买订单（orderType=2）：订单关联的优惠券 creater 必须为当前商家。
     * <p>订单不存在时直接放行，交给上层方法处理。
     */
    private void checkMerchantOrderOwnership(Long orderId) {
        if (orderId == null) {
            return;
        }
        Long merchantId = UserContext.getUser();
        if (merchantId == null) {
            return; // 未登录交给上层处理
        }
        Order order = getById(orderId);
        if (order == null) {
            return; // 订单不存在交给上层处理
        }
        // 优惠券购买订单：校验优惠券 creater
        if (order.getOrderType() != null && order.getOrderType() == 2) {
            if (order.getCouponId() == null) {
                throw new BizIllegalException("无权操作他人订单");
            }
            Coupon coupon = couponMapper.selectById(order.getCouponId());
            if (coupon == null || coupon.getCreater() == null
                    || !coupon.getCreater().equals(merchantId)) {
                throw new BizIllegalException("无权操作他人订单");
            }
            return;
        }
        // 商品订单（普通/秒杀）：校验 order_detail 中是否包含商家的商品（按 merchant_id 快照校验）
        Long count = Long.valueOf(detailService.lambdaQuery()
                .eq(OrderDetail::getOrderId, orderId)
                .eq(OrderDetail::getMerchantId, merchantId)
                .count());
        if (count == null || count == 0) {
            throw new BizIllegalException("无权操作他人订单");
        }
    }

    @Override
    public PageDTO<MerchantOrderVO> queryMerchantOrderPage(int page, int size, Integer status, String beginTime, String endTime) {
        // 按 order_detail.merchant_id 直接查询（商品物理删除后仍可查到订单）
        Long merchantId = UserContext.getUser();
        List<OrderDetail> merchantDetails = detailService.lambdaQuery()
                .eq(OrderDetail::getMerchantId, merchantId).list();
        List<Long> merchantOrderIds = merchantDetails.stream()
                .map(OrderDetail::getOrderId).distinct().collect(Collectors.toList());
        if (merchantOrderIds.isEmpty()) {
            return PageDTO.of(0L, 1, Collections.emptyList());
        }

        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();
        wrapper.in(Order::getId, merchantOrderIds);
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
        // 商家订单所有权校验：只能查看包含自己商品的订单（或自己创建的优惠券订单）
        checkMerchantOrderOwnership(orderId);
        Order order = getById(orderId);
        if (order == null) {
            return null;
        }
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        MerchantOrderVO vo = new MerchantOrderVO()
                .setId(order.getId())
                .setTotalFee(order.getTotalFee())
                .setPostFee(order.getPostFee())
                .setPaymentType(order.getPaymentType())
                .setUserId(order.getUserId())
                .setStatus(order.getStatus())
                .setStatusText(getStatusText(order.getStatus()))
                .setOrderType(order.getOrderType() != null ? order.getOrderType() : 1)
                .setCreateTime(order.getCreateTime() != null ? order.getCreateTime().format(formatter) : null)
                .setPayTime(order.getPayTime() != null ? order.getPayTime().format(formatter) : null)
                .setConsignTime(order.getConsignTime() != null ? order.getConsignTime().format(formatter) : null)
                .setEndTime(order.getEndTime() != null ? order.getEndTime().format(formatter) : null)
                .setCloseTime(order.getCloseTime() != null ? order.getCloseTime().format(formatter) : null)
                .setCommentTime(order.getCommentTime() != null ? order.getCommentTime().format(formatter) : null);
        if (order.getOrderType() != null && order.getOrderType() == 2) {
            vo.setItemName("优惠券购买订单");
            vo.setItemCount(1);
        } else {
            List<OrderDetail> details = detailService.lambdaQuery()
                    .eq(OrderDetail::getOrderId, orderId).list();
            if (details != null && !details.isEmpty()) {
                // 秒杀订单商品名加 [秒杀] 前缀，与列表页展示一致
                String namePrefix = (order.getOrderType() != null && order.getOrderType() == 3) ? "[秒杀] " : "";
                vo.setItemName(namePrefix + details.get(0).getName());
                vo.setItemCount(details.stream().mapToInt(OrderDetail::getNum).sum());
                List<MerchantOrderVO.OrderDetailVO> detailVOList = details.stream().map(d -> {
                    MerchantOrderVO.OrderDetailVO dvo = new MerchantOrderVO.OrderDetailVO();
                    dvo.setItemId(d.getItemId());
                    dvo.setSkuId(d.getSkuId());
                    dvo.setName(d.getName());
                    dvo.setPrice(d.getPrice());
                    dvo.setCostPrice(d.getCostPrice());
                    dvo.setNum(d.getNum());
                    dvo.setImage(d.getImage());
                    return dvo;
                }).collect(Collectors.toList());
                vo.setOrderDetails(detailVOList);
            }
        }
        // 填充物流信息（含运费，供商家后台统计/详情查看；前台用户接口不会走到这里）
        OrderLogistics logistics = orderLogisticsService.getById(orderId);
        if (logistics != null) {
            MerchantOrderVO.LogisticsVO lvo = new MerchantOrderVO.LogisticsVO();
            lvo.setLogisticsType(logistics.getLogisticsType());
            lvo.setLogisticsNumber(logistics.getLogisticsNumber());
            lvo.setLogisticsCompany(logistics.getLogisticsCompany());
            lvo.setTrackingUrl(logistics.getTrackingUrl());
            lvo.setShipFromText(logistics.getShipFromText());
            lvo.setContact(logistics.getContact());
            lvo.setMobile(logistics.getMobile());
            lvo.setProvince(logistics.getProvince());
            lvo.setCity(logistics.getCity());
            lvo.setTown(logistics.getTown());
            lvo.setStreet(logistics.getStreet());
            lvo.setWeight(logistics.getWeight());
            lvo.setShippingFee(logistics.getShippingFee());
            vo.setLogistics(lvo);
        }
        return vo;
    }

    /**
     * 发货（模拟：点击发货后商品立即变成到货状态）
     */
    @Override
    public void shipOrder(Long orderId, ShipOrderDTO shipDTO) {
        // 商家订单所有权校验：只能发货包含自己商品的订单
        checkMerchantOrderOwnership(orderId);
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
        // 更新物流记录（物流公司/单号等），下单时已创建 order_logistics
        OrderLogistics logistics = orderLogisticsService.getById(orderId);
        if (logistics != null && shipDTO != null) {
            boolean dirty = false;
            if (shipDTO.getLogisticsCompany() != null && !shipDTO.getLogisticsCompany().isEmpty()) {
                logistics.setLogisticsCompany(shipDTO.getLogisticsCompany());
                dirty = true;
            }
            if (shipDTO.getLogisticsCompanyCode() != null && !shipDTO.getLogisticsCompanyCode().isEmpty()) {
                logistics.setLogisticsCompanyCode(shipDTO.getLogisticsCompanyCode());
                dirty = true;
            }
            if (shipDTO.getLogisticsNumber() != null && !shipDTO.getLogisticsNumber().isEmpty()) {
                logistics.setLogisticsNumber(shipDTO.getLogisticsNumber());
                dirty = true;
            }
            if (shipDTO.getTrackingUrl() != null && !shipDTO.getTrackingUrl().isEmpty()) {
                logistics.setTrackingUrl(shipDTO.getTrackingUrl());
                dirty = true;
            }
            if (dirty) {
                logistics.setUpdateTime(LocalDateTime.now());
                orderLogisticsService.updateById(logistics);
            }
        }
        // 模拟发货：直接从"已付款未发货"变为"已到货待确认"
        order.setStatus(3); // 已发货（模拟场景下相当于到货）
        order.setConsignTime(LocalDateTime.now());
        updateById(order);
        log.info("订单发货成功（模拟到货）: orderId={}, 物流单号={}", orderId,
                logistics != null ? logistics.getLogisticsNumber() : null);
    }

    /**
     * 退款（商家后台操作，商品订单和优惠券订单通用）
     */
    @Override
    public void refundOrder(Long orderId) {
        // 商家订单所有权校验：只能退款包含自己商品的订单（或自己创建的优惠券订单）
        checkMerchantOrderOwnership(orderId);
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
        // 按 order_detail.merchant_id 直接查询（商品物理删除后仍可查到订单）
        Long merchantId = UserContext.getUser();
        List<OrderDetail> merchantDetails = detailService.lambdaQuery()
                .eq(OrderDetail::getMerchantId, merchantId).list();
        List<Long> merchantOrderIds = merchantDetails.stream()
                .map(OrderDetail::getOrderId).distinct().collect(Collectors.toList());
        if (merchantOrderIds.isEmpty()) {
            OrderStatsDTO empty = new OrderStatsDTO();
            empty.setTodayNew(0L); empty.setPendingShip(0L); empty.setShipped(0L);
            empty.setRefunding(0L); empty.setTodaySales(0L);
            return empty;
        }

        LocalDateTime todayStart = LocalDateTime.of(LocalDate.now(), LocalTime.MIN);
        LocalDateTime todayEnd = LocalDateTime.of(LocalDate.now(), LocalTime.MAX);

        OrderStatsDTO stats = new OrderStatsDTO();
        stats.setTodayNew(Long.valueOf(lambdaQuery()
                .in(Order::getId, merchantOrderIds)
                .ge(Order::getCreateTime, todayStart)
                .le(Order::getCreateTime, todayEnd)
                .count()));
        stats.setPendingShip(Long.valueOf(lambdaQuery()
                .in(Order::getId, merchantOrderIds)
                .eq(Order::getStatus, 2).eq(Order::getOrderType, 1).count()));
        stats.setShipped(Long.valueOf(lambdaQuery()
                .in(Order::getId, merchantOrderIds)
                .eq(Order::getStatus, 3).eq(Order::getOrderType, 1).count()));
        stats.setRefunding(Long.valueOf(lambdaQuery()
                .in(Order::getId, merchantOrderIds)
                .eq(Order::getStatus, 7).count()));
        List<Order> todayOrders = lambdaQuery()
                .in(Order::getId, merchantOrderIds)
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
        // 按 order_detail.merchant_id 直接查询（商品物理删除后仍可查到订单）
        Long merchantId = UserContext.getUser();
        List<OrderDetail> merchantDetails = detailService.lambdaQuery()
                .eq(OrderDetail::getMerchantId, merchantId).list();
        List<Long> merchantOrderIds = merchantDetails.stream()
                .map(OrderDetail::getOrderId).distinct().collect(Collectors.toList());
        if (merchantOrderIds.isEmpty()) {
            return Collections.emptyList();
        }

        List<SalesTrendDTO> result = new ArrayList<>();
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd");
        for (int i = days - 1; i >= 0; i--) {
            LocalDate date = LocalDate.now().minusDays(i);
            LocalDateTime dayStart = LocalDateTime.of(date, LocalTime.MIN);
            LocalDateTime dayEnd = LocalDateTime.of(date, LocalTime.MAX);

            SalesTrendDTO dto = new SalesTrendDTO();
            dto.setDate(date.format(formatter));
            dto.setOrders(Long.valueOf(lambdaQuery()
                    .in(Order::getId, merchantOrderIds)
                    .ge(Order::getCreateTime, dayStart)
                    .le(Order::getCreateTime, dayEnd)
                    .ne(Order::getStatus, 5)
                    .count()));
            List<Order> dayOrders = lambdaQuery()
                    .in(Order::getId, merchantOrderIds)
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
        // 按 order_detail.merchant_id 直接查询（商品物理删除后仍可查到订单）
        Long merchantId = UserContext.getUser();
        List<OrderDetail> all = detailService.lambdaQuery()
                .eq(OrderDetail::getMerchantId, merchantId).list();
        if (all.isEmpty()) {
            return Collections.emptyList();
        }
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

    /**
     * 商家后台-利润统计（按时间范围）
     * <p>仅统计已完成订单（状态 4=交易成功 / 6=已评价），不含已关闭（5）
     * <p>销售额 = order.totalFee 之和（优惠后金额，不含运费）
     * <p>商品成本 = order_detail.cost_price * num 之和
     * <p>运费成本 = order_logistics.shipping_fee 之和
     * <p>优惠折扣 = order.discount_amount 之和
     * <p>毛利润 = 销售额 - 商品成本
     * <p>净利润 = 销售额 - 商品成本 - 运费
     */
    @Override
    public ProfitStatsDTO getProfitStats(Integer days) {
        // 1. 构建时间范围
        LocalDateTime startTime = null;
        if (days != null && days > 0) {
            startTime = LocalDateTime.of(LocalDate.now().minusDays(days - 1L), LocalTime.MIN);
        }
        // 2. 按 order_detail.merchant_id 直接查询（商品物理删除后仍可查到订单）
        Long merchantId = UserContext.getUser();
        List<OrderDetail> merchantDetails = detailService.lambdaQuery()
                .eq(OrderDetail::getMerchantId, merchantId).list();
        List<Long> merchantOrderIds = merchantDetails.stream()
                .map(OrderDetail::getOrderId).distinct().collect(Collectors.toList());
        if (merchantOrderIds.isEmpty()) {
            ProfitStatsDTO empty = new ProfitStatsDTO();
            empty.setOrderCount(0); empty.setTotalSales(0L); empty.setTotalCost(0L);
            empty.setTotalShippingFee(0L); empty.setTotalDiscount(0L);
            empty.setGrossProfit(0L); empty.setNetProfit(0L); empty.setProfitMargin(0.0);
            return empty;
        }
        // 3. 查询已完成订单（状态 4/6），排除优惠券购买订单（orderType=2）
        List<Order> orders = lambdaQuery()
                .in(Order::getId, merchantOrderIds)
                .in(Order::getStatus, 4, 6)
                .ne(Order::getOrderType, 2)
                .ge(startTime != null, Order::getCreateTime, startTime)
                .list();
        if (orders.isEmpty()) {
            ProfitStatsDTO empty = new ProfitStatsDTO();
            empty.setOrderCount(0); empty.setTotalSales(0L); empty.setTotalCost(0L);
            empty.setTotalShippingFee(0L); empty.setTotalDiscount(0L);
            empty.setGrossProfit(0L); empty.setNetProfit(0L); empty.setProfitMargin(0.0);
            return empty;
        }
        // 4. 汇总销售额和优惠折扣
        long totalSales = orders.stream()
                .mapToLong(o -> o.getTotalFee() != null ? o.getTotalFee() : 0).sum();
        long totalDiscount = orders.stream()
                .mapToLong(o -> o.getDiscountAmount() != null ? o.getDiscountAmount() : 0).sum();
        // 5. 查询订单详情（只统计当前商家的商品，按 merchant_id 快照过滤），汇总商品成本（cost_price * num）
        List<Long> orderIds = orders.stream().map(Order::getId).collect(Collectors.toList());
        List<OrderDetail> details = detailService.lambdaQuery()
                .in(OrderDetail::getOrderId, orderIds)
                .eq(OrderDetail::getMerchantId, merchantId).list();
        long totalCost = details.stream()
                .mapToLong(d -> (d.getCostPrice() != null ? d.getCostPrice() : 0) * (d.getNum() != null ? d.getNum() : 0))
                .sum();
        // 6. 查询物流记录，汇总运费
        List<OrderLogistics> logistics = orderLogisticsService.lambdaQuery()
                .in(OrderLogistics::getOrderId, orderIds).list();
        long totalShippingFee = logistics.stream()
                .mapToLong(l -> l.getShippingFee() != null ? l.getShippingFee() : 0).sum();
        // 7. 计算利润
        long grossProfit = totalSales - totalCost;
        long netProfit = totalSales - totalCost - totalShippingFee;
        double profitMargin = totalSales > 0 ? (double) netProfit * 100.0 / totalSales : 0.0;
        // 8. 封装结果
        ProfitStatsDTO stats = new ProfitStatsDTO();
        stats.setOrderCount(orders.size());
        stats.setTotalSales(totalSales);
        stats.setTotalCost(totalCost);
        stats.setTotalShippingFee(totalShippingFee);
        stats.setTotalDiscount(totalDiscount);
        stats.setGrossProfit(grossProfit);
        stats.setNetProfit(netProfit);
        stats.setProfitMargin(Math.round(profitMargin * 100.0) / 100.0);
        return stats;
    }

    /**
     * 商家后台-利润趋势（按天）
     * <p>仅统计已完成订单（状态 4/6），按订单创建时间归到每一天
     */
    @Override
    public List<ProfitTrendDTO> getProfitTrend(Integer days) {
        if (days == null || days <= 0) {
            days = 7;
        }
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd");
        // 1. 按 order_detail.merchant_id 直接查询（商品物理删除后仍可查到订单）
        Long merchantId = UserContext.getUser();
        List<OrderDetail> merchantDetails = detailService.lambdaQuery()
                .eq(OrderDetail::getMerchantId, merchantId).list();
        List<Long> merchantOrderIds = merchantDetails.stream()
                .map(OrderDetail::getOrderId).distinct().collect(Collectors.toList());
        if (merchantOrderIds.isEmpty()) {
            return Collections.emptyList();
        }
        // 2. 查询近 N 天已完成订单（状态 4/6，排除优惠券购买订单），仅含商家订单
        LocalDateTime startTime = LocalDateTime.of(LocalDate.now().minusDays(days - 1L), LocalTime.MIN);
        List<Order> orders = lambdaQuery()
                .in(Order::getId, merchantOrderIds)
                .in(Order::getStatus, 4, 6)
                .ne(Order::getOrderType, 2)
                .ge(Order::getCreateTime, startTime)
                .list();
        List<Long> orderIds = orders.stream().map(Order::getId).collect(Collectors.toList());
        // 3. 一次性查询订单详情（仅统计当前商家商品，按 merchant_id 快照过滤）和物流记录
        Map<Long, List<OrderDetail>> detailMap = orderIds.isEmpty()
                ? Collections.emptyMap()
                : detailService.lambdaQuery()
                    .in(OrderDetail::getOrderId, orderIds)
                    .eq(OrderDetail::getMerchantId, merchantId).list().stream()
                    .collect(Collectors.groupingBy(OrderDetail::getOrderId));
        Map<Long, OrderLogistics> logisticsMap = orderIds.isEmpty()
                ? Collections.emptyMap()
                : orderLogisticsService.lambdaQuery().in(OrderLogistics::getOrderId, orderIds).list().stream()
                    .collect(Collectors.toMap(OrderLogistics::getOrderId, l -> l, (a, b) -> a));
        // 4. 按天聚合
        Map<String, ProfitTrendDTO> dayMap = new LinkedHashMap<>();
        for (int i = days - 1; i >= 0; i--) {
            LocalDate date = LocalDate.now().minusDays(i);
            ProfitTrendDTO dto = new ProfitTrendDTO();
            dto.setDate(date.format(formatter));
            dto.setSales(0L);
            dto.setCost(0L);
            dto.setShippingFee(0L);
            dto.setNetProfit(0L);
            dayMap.put(dto.getDate(), dto);
        }
        for (Order order : orders) {
            if (order.getCreateTime() == null) continue;
            String key = order.getCreateTime().toLocalDate().format(formatter);
            ProfitTrendDTO dto = dayMap.get(key);
            if (dto == null) continue;
            long sales = order.getTotalFee() != null ? order.getTotalFee() : 0;
            long cost = 0L;
            List<OrderDetail> ds = detailMap.getOrDefault(order.getId(), Collections.emptyList());
            for (OrderDetail d : ds) {
                cost += (long) (d.getCostPrice() != null ? d.getCostPrice() : 0) * (d.getNum() != null ? d.getNum() : 0);
            }
            OrderLogistics lg = logisticsMap.get(order.getId());
            long shipping = lg != null && lg.getShippingFee() != null ? lg.getShippingFee() : 0L;
            dto.setSales(dto.getSales() + sales);
            dto.setCost(dto.getCost() + cost);
            dto.setShippingFee(dto.getShippingFee() + shipping);
            dto.setNetProfit(dto.getNetProfit() + (sales - cost - shipping));
        }
        return new ArrayList<>(dayMap.values());
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
        // 商家订单所有权校验：只能审核自己商品订单的退货
        checkMerchantOrderOwnership(orderId);
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
        // 商家订单所有权校验：只能拒绝自己商品订单的退货
        checkMerchantOrderOwnership(orderId);
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
     * 查询用户所有已完成订单中的 item_id 去重列表
     * 已完成订单状态：4（交易成功）、6（已评价）
     * 仅查询商品订单（orderType=1）和秒杀商品订单（orderType=3），排除优惠券购买订单
     * 用于 US-AT-17 排除已购买的商品
     */
    @Override
    public List<Long> queryUserOrderItemIds(Long userId) {
        if (userId == null) {
            return CollUtils.emptyList();
        }
        // 1.查询用户已完成的订单（交易成功=4、已评价=6）
        List<Order> orders = lambdaQuery()
                .eq(Order::getUserId, userId)
                .in(Order::getStatus, 4, 6)
                .in(Order::getOrderType, 1, 3)
                .list();
        if (CollUtils.isEmpty(orders)) {
            return CollUtils.emptyList();
        }
        // 2.提取订单ID
        Set<Long> orderIds = orders.stream().map(Order::getId).collect(Collectors.toSet());
        // 3.查询订单详情，提取 item_id 去重
        List<OrderDetail> details = detailService.lambdaQuery()
                .in(OrderDetail::getOrderId, orderIds)
                .list();
        if (CollUtils.isEmpty(details)) {
            return CollUtils.emptyList();
        }
        return details.stream()
                .map(OrderDetail::getItemId)
                .filter(itemId -> itemId != null)
                .distinct()
                .collect(Collectors.toList());
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
        wrapper.eq(Order::getUserId, userId)
               .eq(Order::getUserDeleted, 0);  // 过滤用户已删除的订单
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

    /**
     * 商品被物理删除时，标记所有引用该商品的 order_detail 快照
     * <p>将 name 改为 "【原商品名】商品已删除"，image 改为占位图。
     * <p>幂等设计：name NOT LIKE '【%】商品已删除' 避免重复添加前缀。
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public void markItemDeletedInOrders(Long itemId, String itemName) {
        if (itemId == null) {
            return;
        }
        // 查询所有引用该商品且未标记过的订单详情
        List<OrderDetail> details = detailService.lambdaQuery()
                .eq(OrderDetail::getItemId, itemId)
                .notLike(OrderDetail::getName, "】商品已删除")
                .list();
        if (details == null || details.isEmpty()) {
            log.info("商品删除标记订单快照：无引用记录, itemId={}", itemId);
            return;
        }
        // 拼接删除标记名（保留原商品名便于追溯）
        String safeName = (itemName == null || itemName.trim().isEmpty())
                ? "商品" : itemName.trim();
        String deletedName = "【" + safeName + "】商品已删除";
        String placeholderImage = "/uploads/items/deleted.jpg";
        // 批量更新
        detailService.lambdaUpdate()
                .eq(OrderDetail::getItemId, itemId)
                .notLike(OrderDetail::getName, "】商品已删除")
                .set(OrderDetail::getName, deletedName)
                .set(OrderDetail::getImage, placeholderImage)
                .update();
        log.info("商品删除标记订单快照成功: itemId={}, 更新记录数={}", itemId, details.size());
    }

    /**
     * 允许用户删除的订单状态：4=交易成功、5=已关闭、6=已评价、8=退货被拒绝
     */
    private static final List<Integer> DELETABLE_STATUS = java.util.Arrays.asList(4, 5, 6, 8);

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteOrder(Long orderId) {
        Long userId = UserContext.getUser();
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }
        if (!order.getUserId().equals(userId)) {
            throw new BizIllegalException("无权操作他人订单");
        }
        if (!DELETABLE_STATUS.contains(order.getStatus())) {
            throw new BizIllegalException("当前订单状态不允许删除，仅允许删除已完成/已关闭/已评价/退货被拒绝的订单");
        }
        if (order.getUserDeleted() != null && order.getUserDeleted() == 1) {
            return; // 已在回收站，幂等返回
        }
        boolean success = lambdaUpdate()
                .set(Order::getUserDeleted, 1)
                .eq(Order::getId, orderId)
                .eq(Order::getUserId, userId)
                .eq(Order::getUserDeleted, 0)
                .update();
        if (success) {
            log.info("用户删除订单: orderId={}, userId={}", orderId, userId);
        }
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public int batchDeleteOrders(List<Long> orderIds) {
        if (orderIds == null || orderIds.isEmpty()) {
            return 0;
        }
        Long userId = UserContext.getUser();
        // 查询这些订单中属于当前用户、状态允许删除、且未删除的
        List<Order> orders = lambdaQuery()
                .in(Order::getId, orderIds)
                .eq(Order::getUserId, userId)
                .in(Order::getStatus, DELETABLE_STATUS)
                .eq(Order::getUserDeleted, 0)
                .list();
        if (orders.isEmpty()) {
            return 0;
        }
        List<Long> validIds = orders.stream().map(Order::getId).collect(Collectors.toList());
        boolean success = lambdaUpdate()
                .set(Order::getUserDeleted, 1)
                .in(Order::getId, validIds)
                .eq(Order::getUserId, userId)
                .eq(Order::getUserDeleted, 0)
                .update();
        if (success) {
            log.info("用户批量删除订单: ids={}, userId={}, 数量={}", validIds, userId, validIds.size());
            return validIds.size();
        }
        return 0;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void restoreOrder(Long orderId) {
        Long userId = UserContext.getUser();
        Order order = getById(orderId);
        if (order == null) {
            throw new BizIllegalException("订单不存在");
        }
        if (!order.getUserId().equals(userId)) {
            throw new BizIllegalException("无权操作他人订单");
        }
        if (order.getUserDeleted() == null || order.getUserDeleted() == 0) {
            return; // 不在回收站，幂等返回
        }
        boolean success = lambdaUpdate()
                .set(Order::getUserDeleted, 0)
                .eq(Order::getId, orderId)
                .eq(Order::getUserId, userId)
                .eq(Order::getUserDeleted, 1)
                .update();
        if (success) {
            log.info("用户恢复订单: orderId={}, userId={}", orderId, userId);
        }
    }

    @Override
    public PageDTO<MerchantOrderVO> queryTrashOrderPage(Long userId, int page, int size) {
        LambdaQueryWrapper<Order> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Order::getUserId, userId)
               .eq(Order::getUserDeleted, 1)
               .orderByDesc(Order::getUpdateTime);
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
