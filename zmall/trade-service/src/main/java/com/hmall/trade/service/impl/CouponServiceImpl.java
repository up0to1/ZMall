package com.hmall.trade.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmall.common.domain.PageDTO;
import com.hmall.api.dto.CouponDTO;
import com.hmall.api.dto.CouponStatsDTO;
import com.hmall.api.vo.CouponVO;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.config.RedisConstants;
import com.hmall.common.config.RedisIdWorker;
import com.hmall.common.constants.MqConstants;
import com.hmall.common.utils.RabbitMqHelper;
import com.hmall.common.utils.UserContext;
import com.hmall.trade.domain.po.Coupon;
import com.hmall.trade.domain.po.CouponItem;
import com.hmall.trade.domain.po.SeckillCoupon;
import com.hmall.trade.domain.po.UserCoupon;
import com.hmall.trade.mapper.CouponItemMapper;
import com.hmall.trade.mapper.CouponMapper;
import com.hmall.trade.mapper.SeckillCouponMapper;
import com.hmall.trade.mapper.UserCouponMapper;
import com.hmall.trade.service.ICouponService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class CouponServiceImpl implements ICouponService {

    private final CouponMapper couponMapper;
    private final CouponItemMapper couponItemMapper;
    private final UserCouponMapper userCouponMapper;
    private final SeckillCouponMapper seckillCouponMapper;
    private final RedisIdWorker redisIdWorker;
    private final StringRedisTemplate stringRedisTemplate;
    private final RabbitMqHelper rabbitMqHelper;
    private static final DateTimeFormatter FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    // ========== 后台管理 ==========

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void createCoupon(CouponDTO dto) {
        validateCoupon(dto);
        Coupon coupon = buildCoupon(dto);
        coupon.setStatus(1); // 默认上架
        couponMapper.insert(coupon);
        // 保存优惠券-商品关联
        saveCouponItems(coupon.getId(), dto);
        // 如果是秒杀券，创建秒杀优惠券记录
        if (dto.getCouponType() != null && dto.getCouponType() == 2) {
            saveSeckillCoupon(coupon.getId(), dto);
        }
        // 发送自动下架延迟消息
        scheduleAutoOffShelf(coupon);
        log.info("优惠券创建成功: couponId={}, name={}, couponType={}", coupon.getId(), coupon.getName(), coupon.getCouponType());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void updateCoupon(Long id, CouponDTO dto) {
        validateCoupon(dto);
        Coupon existing = couponMapper.selectById(id);
        if (existing == null) {
            throw new BadRequestException("优惠券不存在");
        }
        Coupon coupon = buildCoupon(dto);
        coupon.setId(id);
        coupon.setStatus(existing.getStatus()); // 保留原状态
        couponMapper.updateById(coupon);
        // 更新优惠券-商品关联：先删后增
        couponItemMapper.delete(new LambdaQueryWrapper<CouponItem>().eq(CouponItem::getCouponId, id));
        saveCouponItems(id, dto);
        // 处理秒杀优惠券记录
        if (dto.getCouponType() != null && dto.getCouponType() == 2) {
            // 秒杀券：更新或创建秒杀记录
            SeckillCoupon existingSeckill = seckillCouponMapper.selectById(id);
            if (existingSeckill != null) {
                updateSeckillCoupon(id, dto);
            } else {
                saveSeckillCoupon(id, dto);
            }
        } else {
            // 普通券：删除可能存在的秒杀记录
            seckillCouponMapper.deleteById(id);
        }
        // 重新调度自动下架
        scheduleAutoOffShelf(coupon);
        log.info("优惠券更新成功: couponId={}", id);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deleteCoupon(Long id) {
        Coupon coupon = couponMapper.selectById(id);
        if (coupon == null) {
            throw new BadRequestException("优惠券不存在");
        }
        // 检查是否有用户已领取且未过期未退款的优惠券
        Long activeCount = Long.valueOf(userCouponMapper.selectCount(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getCouponId, id)
                        .in(UserCoupon::getStatus, 1, 2, 3))); // 未使用、已下单、已支付
        if (activeCount != null && activeCount > 0) {
            throw new BadRequestException("该优惠券有用户正在使用中，无法删除，请先下架");
        }
        // 删除优惠券-商品关联
        couponItemMapper.delete(new LambdaQueryWrapper<CouponItem>().eq(CouponItem::getCouponId, id));
        // 删除已过期/已退款的用户优惠券记录
        userCouponMapper.delete(new LambdaQueryWrapper<UserCoupon>().eq(UserCoupon::getCouponId, id));
        // 删除优惠券
        couponMapper.deleteById(id);
        log.info("优惠券删除成功: couponId={}", id);
    }

    @Override
    public PageDTO<CouponVO> queryCouponPage(int page, int size, Integer status, Integer couponType) {
        LambdaQueryWrapper<Coupon> wrapper = new LambdaQueryWrapper<Coupon>()
                .eq(status != null, Coupon::getStatus, status)
                .eq(couponType != null, Coupon::getCouponType, couponType)
                .orderByDesc(Coupon::getCreateTime);
        Page<Coupon> couponPage = couponMapper.selectPage(new Page<>(page, size), wrapper);

        List<CouponVO> list = couponPage.getRecords().stream().map(this::toCouponVO).collect(Collectors.toList());
        return PageDTO.of(couponPage.getTotal(), couponPage.getPages(), list);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void updateCouponStatus(Long id, Integer status) {
        Coupon coupon = couponMapper.selectById(id);
        if (coupon == null) {
            throw new BadRequestException("优惠券不存在");
        }
        coupon.setStatus(status);
        couponMapper.updateById(coupon);
        // 上架时重新调度自动下架
        if (status == 1) {
            scheduleAutoOffShelf(coupon);
        }
        log.info("优惠券状态变更: couponId={}, status={}", id, status);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void updateCouponType(Long id, Integer couponType) {
        Coupon coupon = couponMapper.selectById(id);
        if (coupon == null) {
            throw new BadRequestException("优惠券不存在");
        }
        if (couponType == null || (couponType != 1 && couponType != 2)) {
            throw new BadRequestException("无效的优惠券类别");
        }
        // 如果从秒杀券改为普通券，检查是否已有预热信息
        if (coupon.getCouponType() != null && coupon.getCouponType() == 2 && couponType == 1) {
            // 已有用户领取的秒杀券不允许改为普通券
            Long activeCount = Long.valueOf(userCouponMapper.selectCount(
                    new LambdaQueryWrapper<UserCoupon>()
                            .eq(UserCoupon::getCouponId, id)
                            .in(UserCoupon::getStatus, 1, 2, 3)));
            if (activeCount != null && activeCount > 0) {
                throw new BadRequestException("该优惠券有用户正在使用中，不允许改为普通券");
            }
        }
        coupon.setCouponType(couponType);
        couponMapper.updateById(coupon);
        // 如果改为普通券，删除秒杀记录
        if (couponType == 1) {
            seckillCouponMapper.deleteById(id);
        }
        log.info("优惠券类别变更: couponId={}, couponType={}", id, couponType);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void setSeckillCoupon(Long id, CouponDTO dto) {
        Coupon coupon = couponMapper.selectById(id);
        if (coupon == null) {
            throw new BadRequestException("优惠券不存在");
        }
        // 校验秒杀信息
        if (dto.getSeckillStock() == null || dto.getSeckillStock() <= 0) {
            throw new BadRequestException("秒杀库存必须大于0");
        }
        // 校验秒杀库存不能超过优惠券发行总量
        if (coupon.getTotalCount() != null && dto.getSeckillStock() > coupon.getTotalCount()) {
            throw new BadRequestException("秒杀库存(" + dto.getSeckillStock() + ")不能超过优惠券发行总量(" + coupon.getTotalCount() + ")");
        }
        if (dto.getRushBeginTime() == null || dto.getRushEndTime() == null) {
            throw new BadRequestException("秒杀开抢时间和结束时间必须设置");
        }
        // 更新优惠券类别为秒杀
        coupon.setCouponType(2);
        // 如果传了有效期，更新有效期
        if (dto.getBeginTime() != null && !dto.getBeginTime().isEmpty()) {
            coupon.setBeginTime(LocalDateTime.parse(dto.getBeginTime(), FORMATTER));
        }
        if (dto.getEndTime() != null && !dto.getEndTime().isEmpty()) {
            coupon.setEndTime(LocalDateTime.parse(dto.getEndTime(), FORMATTER));
        }
        couponMapper.updateById(coupon);
        // 更新或创建秒杀记录
        SeckillCoupon existing = seckillCouponMapper.selectById(id);
        if (existing != null) {
            updateSeckillCoupon(id, dto);
        } else {
            saveSeckillCoupon(id, dto);
        }
        log.info("优惠券设为秒杀成功: couponId={}", id);
    }

    @Override
    public CouponVO getCouponDetail(Long id) {
        Coupon coupon = couponMapper.selectById(id);
        if (coupon == null) {
            return null;
        }
        return toCouponVO(coupon);
    }

    @Override
    public CouponStatsDTO getCouponStats() {
        CouponStatsDTO stats = new CouponStatsDTO();
        stats.setTotalIssued(0);
        stats.setTotalReceived(0);
        stats.setTotalUsed(0);
        couponMapper.selectList(null).forEach(c -> {
            stats.setTotalIssued(stats.getTotalIssued() + (c.getTotalCount() != null ? c.getTotalCount() : 0));
            stats.setTotalReceived(stats.getTotalReceived() + (c.getReceivedCount() != null ? c.getReceivedCount() : 0));
            stats.setTotalUsed(stats.getTotalUsed() + (c.getUsedCount() != null ? c.getUsedCount() : 0));
        });
        stats.setReceiveRate(stats.getTotalIssued() > 0
                ? (double) stats.getTotalReceived() / stats.getTotalIssued() * 100 : 0);
        stats.setUseRate(stats.getTotalReceived() > 0
                ? (double) stats.getTotalUsed() / stats.getTotalReceived() * 100 : 0);
        return stats;
    }

    // ========== 前台用户 ==========

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void receiveCoupon(Long couponId, Long userId) {
        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon == null) {
            throw new BadRequestException("优惠券不存在");
        }
        // 秒杀券走秒杀通道
        if (coupon.getCouponType() != null && coupon.getCouponType() == 2) {
            throw new BadRequestException("秒杀优惠券请通过秒杀通道领取/购买");
        }
        if (coupon.getPurchasePrice() != null && coupon.getPurchasePrice() > 0) {
            throw new BadRequestException("该优惠券需要购买，请使用购买功能");
        }
        validateCouponAvailable(coupon, userId);
        // 免费领取：直接创建user_coupon
        createUserCoupon(couponId, userId, coupon);
        // 更新已领取数量
        coupon.setReceivedCount(coupon.getReceivedCount() + 1);
        couponMapper.updateById(coupon);
        log.info("用户免费领取优惠券成功: userId={}, couponId={}", userId, couponId);
    }

    @Override
    public void purchaseCoupon(Long couponId, Long userId, Integer paymentType) {
        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon == null) {
            throw new BadRequestException("优惠券不存在");
        }
        // 秒杀券走秒杀通道
        if (coupon.getCouponType() != null && coupon.getCouponType() == 2) {
            throw new BadRequestException("秒杀优惠券请通过秒杀通道领取/购买");
        }
        if (coupon.getPurchasePrice() == null || coupon.getPurchasePrice() <= 0) {
            throw new BadRequestException("该优惠券免费，请直接领取");
        }
        validateCouponAvailable(coupon, userId);
        // 校验通过，实际订单创建由OrderServiceImpl.createCouponOrder完成
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void useCoupon(Long couponId, Long userId, Long orderId) {
        UserCoupon userCoupon = userCouponMapper.selectOne(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId)
                        .eq(UserCoupon::getCouponId, couponId)
                        .in(UserCoupon::getStatus, 1, 2));
        if (userCoupon == null) {
            throw new BadRequestException("未找到可用的优惠券");
        }
        // 校验有效期范围
        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon != null && coupon.getBeginTime() != null && coupon.getEndTime() != null) {
            LocalDateTime now = LocalDateTime.now();
            if (now.isBefore(coupon.getBeginTime()) || now.isAfter(coupon.getEndTime())) {
                throw new BadRequestException("优惠券不在有效期内");
            }
        }
        if (userCoupon.getExpireTime() != null && LocalDateTime.now().isAfter(userCoupon.getExpireTime())) {
            userCoupon.setStatus(4); // 已过期
            userCouponMapper.updateById(userCoupon);
            throw new BadRequestException("优惠券已过期");
        }
        userCoupon.setStatus(2);
        userCoupon.setOrderId(orderId);
        userCouponMapper.updateById(userCoupon);
        log.info("优惠券标记为已下单: userId={}, couponId={}, orderId={}", userId, couponId, orderId);
    }

    // ========== 优惠券购买订单回调 ==========

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void deliverCouponOrder(Long orderId, Long userId, Long couponId) {
        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon == null) {
            log.error("优惠券不存在: couponId={}", couponId);
            return;
        }
        // 防止重复创建（基于orderId，支持同一用户购买多张同ID优惠券）
        Long count = Long.valueOf(userCouponMapper.selectCount(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId)
                        .eq(UserCoupon::getCouponId, couponId)
                        .eq(UserCoupon::getOrderId, orderId)));
        if (count != null && count > 0) {
            log.info("用户优惠券已存在，跳过创建: userId={}, couponId={}, orderId={}", userId, couponId, orderId);
            return;
        }
        createUserCoupon(couponId, userId, coupon);
        // 设置orderId关联（付费券购买订单关联）
        UserCoupon latestUc = userCouponMapper.selectOne(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId)
                        .eq(UserCoupon::getCouponId, couponId)
                        .isNull(UserCoupon::getOrderId)
                        .orderByDesc(UserCoupon::getId)
                        .last("LIMIT 1"));
        if (latestUc != null) {
            latestUc.setOrderId(orderId);
            userCouponMapper.updateById(latestUc);
        }
        coupon.setReceivedCount(coupon.getReceivedCount() + 1);
        couponMapper.updateById(coupon);
        log.info("优惠券购买自动发货成功: userId={}, couponId={}, orderId={}", userId, couponId, orderId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void refundCouponOrder(Long orderId, Long userId, Long couponId) {
        UserCoupon userCoupon = userCouponMapper.selectOne(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId)
                        .eq(UserCoupon::getCouponId, couponId)
                        .eq(UserCoupon::getOrderId, orderId));
        if (userCoupon != null) {
            userCouponMapper.deleteById(userCoupon.getId());
            Coupon coupon = couponMapper.selectById(couponId);
            if (coupon != null && coupon.getReceivedCount() > 0) {
                coupon.setReceivedCount(coupon.getReceivedCount() - 1);
                couponMapper.updateById(coupon);
            }
            // 秒杀券退款：回退Redis库存、用户已购计数、订单集合
            if (coupon != null && coupon.getCouponType() != null && coupon.getCouponType() == 2) {
                String stockKey = RedisConstants.SECKILL_COUPON_STOCK_KEY + couponId;
                stringRedisTemplate.opsForValue().increment(stockKey);
                String userCountKey = RedisConstants.SECKILL_COUPON_USER_COUNT_KEY
                        + couponId + ":" + userId;
                stringRedisTemplate.opsForValue().decrement(userCountKey);
                String orderKey = RedisConstants.SECKILL_COUPON_ORDER_KEY + couponId;
                stringRedisTemplate.opsForSet().remove(orderKey, userId.toString());
                log.info("秒杀券退款，已回退Redis库存: couponId={}, userId={}", couponId, userId);
            }
            log.info("优惠券退款成功，已删除领取记录: userId={}, couponId={}, orderId={}", userId, couponId, orderId);
        }
    }

    // ========== 查询优惠券适用商品ID列表 ==========

    @Override
    public List<Long> getCouponItemIds(Long couponId) {
        List<CouponItem> items = couponItemMapper.selectList(
                new LambdaQueryWrapper<CouponItem>().eq(CouponItem::getCouponId, couponId));
        return items.stream().map(CouponItem::getItemId).collect(Collectors.toList());
    }

    @Override
    public PageDTO<CouponVO> queryAvailableCoupons(int page, int size, Integer couponType) {
        LambdaQueryWrapper<Coupon> wrapper = new LambdaQueryWrapper<Coupon>()
                .eq(Coupon::getStatus, 1) // 上架中
                .and(w -> w.ge(Coupon::getEndTime, LocalDateTime.now()) // 固定有效期且未过期
                        .or().isNull(Coupon::getEndTime)) // 或领后N天有效
                .orderByDesc(Coupon::getCreateTime);
        if (couponType != null) {
            wrapper.eq(Coupon::getCouponType, couponType);
        }
        Page<Coupon> couponPage = couponMapper.selectPage(new Page<>(page, size), wrapper);
        List<CouponVO> list = couponPage.getRecords().stream().map(this::toCouponVO).collect(Collectors.toList());
        return PageDTO.of(couponPage.getTotal(), couponPage.getPages(), list);
    }

    @Override
    public List<CouponVO> queryItemCoupons(Long itemId) {
        // 1. 查询适用该商品的优惠券ID（scope_type=2 且关联了该商品）
        List<CouponItem> couponItems = couponItemMapper.selectList(
                new LambdaQueryWrapper<CouponItem>().eq(CouponItem::getItemId, itemId));
        List<Long> couponIds = couponItems.stream().map(CouponItem::getCouponId).collect(Collectors.toList());

        // 2. 查询全品类优惠券（scope_type=1）
        LambdaQueryWrapper<Coupon> allScopeWrapper = new LambdaQueryWrapper<Coupon>()
                .eq(Coupon::getStatus, 1)
                .eq(Coupon::getScopeType, 1)
                .and(w -> w.ge(Coupon::getEndTime, LocalDateTime.now())
                        .or().isNull(Coupon::getEndTime));
        List<Coupon> allScopeCoupons = couponMapper.selectList(allScopeWrapper);

        // 3. 查询部分商品适用的优惠券
        List<Coupon> itemScopeCoupons = Collections.emptyList();
        if (!couponIds.isEmpty()) {
            itemScopeCoupons = couponMapper.selectList(
                    new LambdaQueryWrapper<Coupon>()
                            .in(Coupon::getId, couponIds)
                            .eq(Coupon::getStatus, 1)
                            .and(w -> w.ge(Coupon::getEndTime, LocalDateTime.now())
                                    .or().isNull(Coupon::getEndTime)));
        }

        // 4. 合并
        allScopeCoupons.addAll(itemScopeCoupons);
        return allScopeCoupons.stream().map(this::toCouponVO).collect(Collectors.toList());
    }

    @Override
    public List<CouponVO> queryUserAvailableCoupons(Long userId) {
        // 查询用户已领取且未使用的优惠券
        List<UserCoupon> userCoupons = userCouponMapper.selectList(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId)
                        .eq(UserCoupon::getStatus, 1)); // 1=未使用
        if (userCoupons.isEmpty()) {
            return Collections.emptyList();
        }
        // 过滤已过期的user_coupon（expireTime < now），标记为已过期
        LocalDateTime now = LocalDateTime.now();
        for (UserCoupon uc : userCoupons) {
            if (uc.getExpireTime() != null && now.isAfter(uc.getExpireTime())) {
                uc.setStatus(4); // 已过期
                userCouponMapper.updateById(uc);
            }
        }
        // 重新查询未使用的（排除刚标记过期的）
        List<Long> couponIds = userCoupons.stream()
                .filter(uc -> uc.getStatus() == 1)
                .map(UserCoupon::getCouponId)
                .collect(Collectors.toList());
        if (couponIds.isEmpty()) {
            return Collections.emptyList();
        }
        List<Coupon> coupons = couponMapper.selectList(
                new LambdaQueryWrapper<Coupon>()
                        .in(Coupon::getId, couponIds)
                        .eq(Coupon::getStatus, 1)
                        .and(w -> w.and(w2 -> w2.ge(Coupon::getEndTime, now) // 固定有效期且未过期
                                        .and(w3 -> w3.le(Coupon::getBeginTime, now) // 已到开始时间
                                                .or().isNull(Coupon::getBeginTime))) // 或无开始时间限制
                                .or().isNull(Coupon::getEndTime))); // 领后N天有效
        return coupons.stream().map(this::toCouponVO).collect(Collectors.toList());
    }

    @Override
    public Map<Long, Long> queryUserReceivedCount(Long userId) {
        // 查询用户所有已领取的优惠券（不限状态），按couponId分组计数
        List<UserCoupon> userCoupons = userCouponMapper.selectList(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId));
        return userCoupons.stream()
                .collect(Collectors.groupingBy(UserCoupon::getCouponId, Collectors.counting()));
    }

    // ========== 私有方法 ==========

    /**
     * 保存优惠券-商品关联
     */
    private void saveCouponItems(Long couponId, CouponDTO dto) {
        if (dto.getScopeType() != null && dto.getScopeType() == 2 && dto.getItemIds() != null) {
            for (Long itemId : dto.getItemIds()) {
                CouponItem ci = new CouponItem();
                ci.setCouponId(couponId);
                ci.setItemId(itemId);
                couponItemMapper.insert(ci);
            }
        }
    }

    private void saveSeckillCoupon(Long couponId, CouponDTO dto) {
        SeckillCoupon sc = new SeckillCoupon();
        sc.setCouponId(couponId);
        sc.setSeckillStock(dto.getSeckillStock());
        sc.setMaxPerUser(dto.getMaxPerUser() != null ? dto.getMaxPerUser() : 1);
        if (dto.getRushBeginTime() != null && !dto.getRushBeginTime().isEmpty()) {
            sc.setRushBeginTime(LocalDateTime.parse(dto.getRushBeginTime(), FORMATTER));
        }
        if (dto.getRushEndTime() != null && !dto.getRushEndTime().isEmpty()) {
            sc.setRushEndTime(LocalDateTime.parse(dto.getRushEndTime(), FORMATTER));
        }
        sc.setCreateTime(LocalDateTime.now());
        sc.setUpdateTime(LocalDateTime.now());
        seckillCouponMapper.insert(sc);
    }

    private void updateSeckillCoupon(Long couponId, CouponDTO dto) {
        SeckillCoupon sc = seckillCouponMapper.selectById(couponId);
        if (sc == null) {
            saveSeckillCoupon(couponId, dto);
            return;
        }
        if (dto.getSeckillStock() != null) sc.setSeckillStock(dto.getSeckillStock());
        if (dto.getMaxPerUser() != null) sc.setMaxPerUser(dto.getMaxPerUser());
        if (dto.getRushBeginTime() != null && !dto.getRushBeginTime().isEmpty()) {
            sc.setRushBeginTime(LocalDateTime.parse(dto.getRushBeginTime(), FORMATTER));
        }
        if (dto.getRushEndTime() != null && !dto.getRushEndTime().isEmpty()) {
            sc.setRushEndTime(LocalDateTime.parse(dto.getRushEndTime(), FORMATTER));
        }
        sc.setUpdateTime(LocalDateTime.now());
        seckillCouponMapper.updateById(sc);
    }

    /**
     * 校验优惠券参数
     */
    private void validateCoupon(CouponDTO dto) {
        // 1. 购买价格必须小于优惠价格
        if (dto.getPurchasePrice() != null && dto.getPurchasePrice() > 0) {
            if (dto.getType() == 1) {
                if (dto.getPurchasePrice() >= dto.getDiscountValue()) {
                    throw new BadRequestException("购买价格必须小于优惠券可抵押的优惠金额");
                }
            } else if (dto.getType() == 2) {
                Integer threshold = dto.getThresholdAmount();
                if (threshold != null && threshold > 0) {
                    int maxDiscount = threshold * (100 - dto.getDiscountValue()) / 100;
                    if (dto.getPurchasePrice() >= maxDiscount) {
                        throw new BadRequestException("购买价格必须小于优惠券可抵押的优惠金额");
                    }
                }
            }
        }

        // 2. 可领取/购买时间范围校验
        if (dto.getBeginTime() != null && dto.getEndTime() != null) {
            LocalDateTime beginTime = LocalDateTime.parse(dto.getBeginTime(), FORMATTER);
            LocalDateTime endTime = LocalDateTime.parse(dto.getEndTime(), FORMATTER);
            if (beginTime.isBefore(LocalDateTime.now().plusMinutes(5))) {
                throw new BadRequestException("优惠开始时间请选择5分钟之后");
            }
            if (!endTime.isAfter(beginTime)) {
                throw new BadRequestException("结束时间请选择开始时间之后");
            }
        }

        // 4. 有效期校验
        if (dto.getValidDays() != null && dto.getValidDays() < 0) {
            throw new BadRequestException("有效天数不能为负数");
        }

        // 5. 适用范围校验：部分商品时必须指定商品
        if (dto.getScopeType() != null && dto.getScopeType() == 2) {
            if (dto.getItemIds() == null || dto.getItemIds().isEmpty()) {
                throw new BadRequestException("部分商品适用时，必须指定适用商品");
            }
        }

        // 6. 券类别默认值
        if (dto.getCouponType() == null) {
            dto.setCouponType(1); // 默认普通券
        }

        // 7. 秒杀券校验
        if (dto.getCouponType() != null && dto.getCouponType() == 2) {
            if (dto.getSeckillStock() == null || dto.getSeckillStock() <= 0) {
                throw new BadRequestException("秒杀券的秒杀库存必须大于0");
            }
            if (dto.getTotalCount() != null && dto.getSeckillStock() > dto.getTotalCount()) {
                throw new BadRequestException("秒杀库存(" + dto.getSeckillStock() + ")不能超过发行总量(" + dto.getTotalCount() + ")");
            }
            if (dto.getRushBeginTime() == null || dto.getRushEndTime() == null) {
                throw new BadRequestException("秒杀券必须设置开抢时间和结束时间");
            }
            // 校验：开抢时间必须在当前时间5分钟之后
            LocalDateTime rushBeginTime = LocalDateTime.parse(dto.getRushBeginTime(), FORMATTER);
            LocalDateTime rushEndTime = LocalDateTime.parse(dto.getRushEndTime(), FORMATTER);
            if (rushBeginTime.isBefore(LocalDateTime.now().plusMinutes(5))) {
                throw new BadRequestException("开抢时间请选择5分钟之后");
            }
            if (!rushEndTime.isAfter(rushBeginTime)) {
                throw new BadRequestException("秒杀结束时间必须在开抢时间之后");
            }
        }
    }

    /**
     * 构建Coupon实体
     */
    private Coupon buildCoupon(CouponDTO dto) {
        Coupon coupon = new Coupon();
        coupon.setName(dto.getName());
        coupon.setType(dto.getType());
        coupon.setCouponType(dto.getCouponType() != null ? dto.getCouponType() : 1);
        coupon.setDiscountValue(dto.getDiscountValue());
        coupon.setThresholdAmount(dto.getThresholdAmount() != null ? dto.getThresholdAmount() : 0);
        coupon.setPurchasePrice(dto.getPurchasePrice() != null ? dto.getPurchasePrice() : 0);
        coupon.setScopeType(dto.getScopeType() != null ? dto.getScopeType() : 1);
        coupon.setValidDays(dto.getValidDays());
        coupon.setTotalCount(dto.getTotalCount());
        coupon.setPerUserLimit(dto.getPerUserLimit() != null ? dto.getPerUserLimit() : 1);
        if (dto.getBeginTime() != null && !dto.getBeginTime().isEmpty()) {
            coupon.setBeginTime(LocalDateTime.parse(dto.getBeginTime(), FORMATTER));
        }
        if (dto.getEndTime() != null && !dto.getEndTime().isEmpty()) {
            coupon.setEndTime(LocalDateTime.parse(dto.getEndTime(), FORMATTER));
        }
        return coupon;
    }

    /**
     * 校验优惠券是否可领取/购买（普通券）
     */
    private void validateCouponAvailable(Coupon coupon, Long userId) {
        if (coupon.getStatus() != 1) {
            throw new BadRequestException("优惠券已下架");
        }
        // 普通优惠券：上架即可领取，beginTime/endTime是使用有效期，不是领取时间范围
        // 只校验优惠券是否已过期（endTime已过则不可领取）
        LocalDateTime now = LocalDateTime.now();
        if (coupon.getEndTime() != null && now.isAfter(coupon.getEndTime())) {
            throw new BadRequestException("优惠券已过期");
        }
        if (coupon.getReceivedCount() >= coupon.getTotalCount()) {
            throw new BadRequestException("优惠券已领完");
        }
        Long userReceived = Long.valueOf(userCouponMapper.selectCount(
                new LambdaQueryWrapper<UserCoupon>()
                        .eq(UserCoupon::getUserId, userId)
                        .eq(UserCoupon::getCouponId, coupon.getId())));
        if (userReceived != null && userReceived >= coupon.getPerUserLimit()) {
            throw new BadRequestException("已达到领取上限");
        }
    }

    /**
     * 创建user_coupon记录
     */
    private void createUserCoupon(Long couponId, Long userId, Coupon coupon) {
        UserCoupon userCoupon = new UserCoupon();
        userCoupon.setId(redisIdWorker.nextId(RedisConstants.ID_PREFIX_USER_COUPON));
        userCoupon.setUserId(userId);
        userCoupon.setCouponId(couponId);
        userCoupon.setStatus(1); // 未使用
        userCoupon.setReceiveTime(LocalDateTime.now());
        if (coupon.getValidDays() != null) {
            if (coupon.getValidDays() == 0) {
                userCoupon.setExpireTime(LocalDateTime.now().toLocalDate().atTime(23, 59, 59));
            } else {
                userCoupon.setExpireTime(LocalDateTime.now().plusDays(coupon.getValidDays()));
            }
        }
        userCouponMapper.insert(userCoupon);
    }

    /**
     * 调度自动下架延迟消息
     */
    private void scheduleAutoOffShelf(Coupon coupon) {
        if (coupon.getStatus() != 1 || coupon.getEndTime() == null) {
            return;
        }
        LocalDateTime offShelfTime = coupon.getEndTime();
        LocalDateTime now = LocalDateTime.now();
        long delayMs = Duration.between(now, offShelfTime).toMillis();
        if (delayMs <= 0) {
            coupon.setStatus(0);
            couponMapper.updateById(coupon);
            log.info("优惠券已过优惠期，立即下架: couponId={}", coupon.getId());
            return;
        }
        int delay = (int) Math.min(delayMs, Integer.MAX_VALUE);
        try {
            rabbitMqHelper.sendDelayMessageWithConfirm(
                    MqConstants.COUPON_OFF_SHELF_DELAY_EXCHANGE,
                    MqConstants.COUPON_OFF_SHELF_DELAY_KEY,
                    coupon.getId(),
                    delay,
                    3);
            log.info("已调度优惠券自动下架: couponId={}, delayMs={}", coupon.getId(), delay);
        } catch (Exception e) {
            log.error("调度优惠券自动下架失败: couponId={}", coupon.getId(), e);
        }
    }

    /**
     * 转换为VO
     */
    private CouponVO toCouponVO(Coupon c) {
        CouponVO vo = new CouponVO();
        vo.setId(c.getId());
        vo.setName(c.getName());
        vo.setType(c.getType());
        vo.setTypeText(getTypeText(c.getType()));
        vo.setCouponType(c.getCouponType());
        vo.setCouponTypeText(c.getCouponType() != null && c.getCouponType() == 2 ? "秒杀券" : "普通券");
        vo.setDiscountValue(c.getDiscountValue());
        vo.setThresholdAmount(c.getThresholdAmount());
        vo.setPurchasePrice(c.getPurchasePrice());
        vo.setPurchasePriceText(c.getPurchasePrice() != null && c.getPurchasePrice() > 0
                ? String.format("%.2f元", c.getPurchasePrice() / 100.0) : "免费");
        vo.setScopeType(c.getScopeType());
        vo.setScopeTypeText(c.getScopeType() != null && c.getScopeType() == 1 ? "全部商品" : "部分商品");
        // 查询关联商品ID
        if (c.getScopeType() != null && c.getScopeType() == 2) {
            vo.setItemIds(getCouponItemIds(c.getId()));
        } else {
            vo.setItemIds(Collections.emptyList());
        }
        vo.setValidDays(c.getValidDays());
        vo.setValidDaysText(c.getValidDays() == null ? "永久有效"
                : c.getValidDays() == 0 ? "当天有效"
                : c.getValidDays() + "天内有效");
        vo.setTotalCount(c.getTotalCount());
        vo.setReceivedCount(c.getReceivedCount());
        vo.setUsedCount(c.getUsedCount());
        vo.setPerUserLimit(c.getPerUserLimit());
        vo.setBeginTime(c.getBeginTime() != null ? c.getBeginTime().format(FORMATTER) : null);
        vo.setEndTime(c.getEndTime() != null ? c.getEndTime().format(FORMATTER) : null);
        vo.setStatus(c.getStatus());
        vo.setCreateTime(c.getCreateTime() != null ? c.getCreateTime().format(FORMATTER) : null);
        // 查询秒杀信息
        if (c.getCouponType() != null && c.getCouponType() == 2) {
            SeckillCoupon sc = seckillCouponMapper.selectById(c.getId());
            if (sc != null) {
                vo.setSeckillStock(sc.getSeckillStock());
                vo.setMaxPerUser(sc.getMaxPerUser());
                vo.setRushBeginTime(sc.getRushBeginTime() != null ? sc.getRushBeginTime().format(FORMATTER) : null);
                vo.setRushEndTime(sc.getRushEndTime() != null ? sc.getRushEndTime().format(FORMATTER) : null);
            }
        }
        return vo;
    }

    private String getTypeText(Integer type) {
        if (type == null) return "未知";
        switch (type) {
            case 1: return "满减券";
            case 2: return "折扣券";
            default: return "未知";
        }
    }
}
