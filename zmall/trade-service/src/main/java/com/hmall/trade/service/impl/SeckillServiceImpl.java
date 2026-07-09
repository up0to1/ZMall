package com.hmall.trade.service.impl;

import cn.hutool.json.JSONUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.hmall.api.client.ItemClient;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.PreheatStatusDTO;
import com.hmall.api.dto.SeckillCouponDTO;
import com.hmall.api.dto.SeckillCouponMessage;
import com.hmall.api.dto.SeckillItemDTO;
import com.hmall.api.vo.SeckillCouponVO;
import com.hmall.api.vo.SeckillItemVO;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.config.RedisConstants;
import com.hmall.common.config.RedisIdWorker;
import com.hmall.common.constants.MqConstants;
import com.hmall.common.utils.RabbitMqHelper;
import com.hmall.trade.domain.dto.SeckillOrderMessage;
import com.hmall.trade.domain.dto.SeckillResult;
import com.hmall.trade.domain.po.Coupon;
import com.hmall.trade.domain.po.SeckillCoupon;
import com.hmall.trade.domain.po.SeckillItem;
import com.hmall.trade.mapper.CouponMapper;
import com.hmall.trade.mapper.SeckillCouponMapper;
import com.hmall.trade.mapper.SeckillItemMapper;
import com.hmall.trade.service.ISeckillService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Arrays;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class SeckillServiceImpl implements ISeckillService {

    private final StringRedisTemplate stringRedisTemplate;
    private final RedisIdWorker redisIdWorker;
    private final RabbitMqHelper rabbitMqHelper;
    private final SeckillItemMapper seckillItemMapper;
    private final SeckillCouponMapper seckillCouponMapper;
    private final CouponMapper couponMapper;
    private final ItemClient itemClient;

    private static final DefaultRedisScript<Long> SECKILL_SCRIPT;

    static {
        SECKILL_SCRIPT = new DefaultRedisScript<>();
        SECKILL_SCRIPT.setLocation(new ClassPathResource("seckill.lua"));
        SECKILL_SCRIPT.setResultType(Long.class);
    }

    // ===== 秒杀商品 =====

    @Override
    public SeckillResult seckillItem(Long itemId, Long userId, Long couponId) {
        // 1. 优先从缓存获取秒杀商品信息
        SeckillItem seckillItem = getSeckillItemFromCache(itemId);
        if (seckillItem == null) {
            return SeckillResult.stockNotEnough();
        }
        // 2. 校验是否在开抢时间范围内
        LocalDateTime now = LocalDateTime.now();
        if (now.isBefore(seckillItem.getRushBeginTime())) {
            return SeckillResult.notStarted(); // 未到开抢时间
        }
        if (now.isAfter(seckillItem.getRushEndTime())) {
            return SeckillResult.ended(); // 已过抢购时间
        }

        // 3. 校验优惠券（如果传了couponId）
        if (couponId != null) {
            Coupon coupon = getCouponFromCache(couponId);
            if (coupon == null || coupon.getStatus() != 1) {
                return SeckillResult.stockNotEnough();
            }
        }

        int maxPerUser = seckillItem.getMaxPerUser() != null ? seckillItem.getMaxPerUser() : 1;

        long orderId = redisIdWorker.nextId(RedisConstants.ID_PREFIX_SECKILL);
        Long result = stringRedisTemplate.execute(
                SECKILL_SCRIPT,
                Arrays.asList(
                        RedisConstants.SECKILL_STOCK_KEY,
                        RedisConstants.SECKILL_ORDER_KEY,
                        RedisConstants.SECKILL_USER_COUNT_KEY
                ),
                itemId.toString(), userId.toString(), String.valueOf(maxPerUser));
        int r = result != null ? result.intValue() : 1;
        if (r != 0) {
            return r == 1 ? SeckillResult.stockNotEnough() : SeckillResult.repeatOrder();
        }
        SeckillOrderMessage message = new SeckillOrderMessage(orderId, userId, itemId, couponId);
        rabbitMqHelper.sendMessageWithConfirm(
                MqConstants.SECKILL_DIRECT_EXCHANGE,
                MqConstants.SECKILL_ORDER_KEY,
                message,
                3);
        return SeckillResult.success(orderId);
    }

    @Override
    public SeckillResult querySeckillResult(Long itemId, Long userId) {
        Boolean isMember = stringRedisTemplate.opsForSet()
                .isMember(RedisConstants.SECKILL_ORDER_KEY + itemId, userId.toString());
        if (Boolean.TRUE.equals(isMember)) {
            return SeckillResult.success(-1L);
        }
        String stock = stringRedisTemplate.opsForValue().get(RedisConstants.SECKILL_STOCK_KEY + itemId);
        if (stock == null || Integer.parseInt(stock) <= 0) {
            return SeckillResult.stockNotEnough();
        }
        return SeckillResult.success(null);
    }

    // ===== 秒杀优惠券 =====

    @Override
    public SeckillResult seckillCoupon(Long couponId, Long userId) {
        // 1. 优先从缓存获取秒杀优惠券信息
        SeckillCoupon seckillCoupon = getSeckillCouponFromCache(couponId);
        if (seckillCoupon == null) {
            return SeckillResult.stockNotEnough();
        }
        // 2. 校验是否在开抢时间范围内
        LocalDateTime now = LocalDateTime.now();
        if (now.isBefore(seckillCoupon.getRushBeginTime())) {
            return SeckillResult.notStarted(); // 未到开抢时间
        }
        if (now.isAfter(seckillCoupon.getRushEndTime())) {
            return SeckillResult.ended(); // 已过抢购时间
        }

        // 秒杀优惠券每人限领1张
        int maxPerUser = 1;

        Long result = stringRedisTemplate.execute(
                SECKILL_SCRIPT,
                Arrays.asList(
                        RedisConstants.SECKILL_COUPON_STOCK_KEY,
                        RedisConstants.SECKILL_COUPON_ORDER_KEY,
                        RedisConstants.SECKILL_COUPON_USER_COUNT_KEY
                ),
                couponId.toString(), userId.toString(), String.valueOf(maxPerUser));
        int r = result != null ? result.intValue() : 1;
        if (r != 0) {
            return r == 1 ? SeckillResult.stockNotEnough() : SeckillResult.repeatOrder();
        }

        // 秒杀券：免费领取直接创建user_coupon，付费购买需要创建订单
        Coupon coupon = getCouponFromCache(couponId);
        if (coupon.getPurchasePrice() != null && coupon.getPurchasePrice() > 0) {
            // 付费秒杀券：发送消息创建订单
            SeckillCouponMessage message = new SeckillCouponMessage(couponId, userId);
            rabbitMqHelper.sendMessageWithConfirm(
                    MqConstants.SECKILL_DIRECT_EXCHANGE,
                    MqConstants.SECKILL_COUPON_ORDER_KEY,
                    message,
                    3);
        } else {
            // 免费秒杀券：直接发送消息创建user_coupon
            SeckillCouponMessage message = new SeckillCouponMessage(couponId, userId);
            rabbitMqHelper.sendMessageWithConfirm(
                    MqConstants.SECKILL_DIRECT_EXCHANGE,
                    MqConstants.SECKILL_COUPON_ORDER_KEY,
                    message,
                    3);
        }
        return SeckillResult.success(couponId);
    }

    @Override
    public SeckillResult querySeckillCouponResult(Long couponId, Long userId) {
        Boolean isMember = stringRedisTemplate.opsForSet()
                .isMember(RedisConstants.SECKILL_COUPON_ORDER_KEY + couponId, userId.toString());
        if (Boolean.TRUE.equals(isMember)) {
            return SeckillResult.success(-1L);
        }
        String stock = stringRedisTemplate.opsForValue().get(RedisConstants.SECKILL_COUPON_STOCK_KEY + couponId);
        if (stock == null || Integer.parseInt(stock) <= 0) {
            return SeckillResult.stockNotEnough();
        }
        return SeckillResult.success(null);
    }

    // ===== Admin: 秒杀商品管理 =====

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void createSeckill(SeckillItemDTO dto) {
        // 校验商品必须是秒杀商品
        ItemDTO item = itemClient.queryItemById(dto.getItemId());
        if (item == null) {
            throw new BadRequestException("商品不存在");
        }
        if (item.getItemType() == null || item.getItemType() != 2) {
            throw new BadRequestException("只有秒杀商品才能设置预热信息");
        }
        // 校验秒杀库存不能超过商品库存
        if (dto.getSeckillStock() != null && item.getStock() != null && dto.getSeckillStock() > item.getStock()) {
            throw new BadRequestException("秒杀库存(" + dto.getSeckillStock() + ")不能超过商品库存(" + item.getStock() + ")");
        }

        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        LocalDateTime rushBeginTime = LocalDateTime.parse(dto.getRushBeginTime(), formatter);
        LocalDateTime rushEndTime = LocalDateTime.parse(dto.getRushEndTime(), formatter);

        // 校验：开抢时间必须在当前时间5分钟之后
        if (rushBeginTime.isBefore(LocalDateTime.now().plusMinutes(5))) {
            throw new BadRequestException("开抢时间请选择5分钟之后");
        }

        if (!rushEndTime.isAfter(rushBeginTime)) {
            throw new BadRequestException("秒杀结束时间必须在开抢时间之后");
        }

        SeckillItem exist = seckillItemMapper.selectById(dto.getItemId());
        SeckillItem seckillItem = exist != null ? exist : new SeckillItem();
        seckillItem.setItemId(dto.getItemId());
        seckillItem.setSeckillStock(dto.getSeckillStock());
        seckillItem.setSeckillPrice(dto.getSeckillPrice());
        seckillItem.setMaxPerUser(dto.getMaxPerUser() != null ? dto.getMaxPerUser() : 1);
        seckillItem.setRushBeginTime(rushBeginTime);
        seckillItem.setRushEndTime(rushEndTime);
        if (exist != null) {
            seckillItemMapper.updateById(seckillItem);
        } else {
            seckillItemMapper.insert(seckillItem);
        }
        // 调度秒杀到期自动转普通商品的延迟消息
        scheduleSeckillItemExpire(seckillItem);
        log.info("秒杀商品预热设置成功: itemId={}, stock={}, price={}, rushBeginTime={}",
                dto.getItemId(), dto.getSeckillStock(), dto.getSeckillPrice(), dto.getRushBeginTime());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public int batchCreateSeckill(SeckillItemDTO.BatchCreateRequest request) {
        if (request.getItemIds() == null || request.getItemIds().isEmpty()) {
            throw new BadRequestException("请选择至少一个商品");
        }
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        LocalDateTime rushBeginTime = LocalDateTime.parse(request.getRushBeginTime(), formatter);
        LocalDateTime rushEndTime = LocalDateTime.parse(request.getRushEndTime(), formatter);

        if (rushBeginTime.isBefore(LocalDateTime.now().plusMinutes(5))) {
            throw new BadRequestException("开抢时间请选择5分钟之后");
        }
        if (!rushEndTime.isAfter(rushBeginTime)) {
            throw new BadRequestException("秒杀结束时间必须在开抢时间之后");
        }

        int count = 0;
        for (Long itemId : request.getItemIds()) {
            try {
                // 校验秒杀价格不能超过商品原价
                ItemDTO itemDTO = itemClient.queryItemById(itemId);
                if (itemDTO != null && request.getSeckillPrice() != null && itemDTO.getPrice() != null
                        && request.getSeckillPrice() > itemDTO.getPrice()) {
                    log.warn("批量设置秒杀商品跳过: itemId={}, 秒杀价格({})超过原价({})", itemId, request.getSeckillPrice(), itemDTO.getPrice());
                    continue;
                }
                // 1. 将商品类型设为秒杀商品(itemType=2)
                itemClient.updateItemType(itemId, 2);
                // 2. 创建/更新秒杀记录
                SeckillItem exist = seckillItemMapper.selectById(itemId);
                SeckillItem seckillItem = exist != null ? exist : new SeckillItem();
                seckillItem.setItemId(itemId);
                seckillItem.setSeckillStock(request.getSeckillStock());
                seckillItem.setSeckillPrice(request.getSeckillPrice());
                seckillItem.setMaxPerUser(request.getMaxPerUser() != null ? request.getMaxPerUser() : 1);
                seckillItem.setRushBeginTime(rushBeginTime);
                seckillItem.setRushEndTime(rushEndTime);
                if (exist != null) {
                    seckillItemMapper.updateById(seckillItem);
                } else {
                    seckillItemMapper.insert(seckillItem);
                }
                scheduleSeckillItemExpire(seckillItem);
                count++;
            } catch (Exception e) {
                log.error("批量设置秒杀商品失败: itemId={}", itemId, e);
            }
        }
        log.info("批量设置秒杀商品完成: 成功{}个, 共{}个", count, request.getItemIds().size());
        return count;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void updateSeckill(SeckillItemDTO dto) {
        // 校验秒杀库存不能超过商品库存
        ItemDTO item = itemClient.queryItemById(dto.getItemId());
        if (item != null && dto.getSeckillStock() != null && item.getStock() != null && dto.getSeckillStock() > item.getStock()) {
            throw new BadRequestException("秒杀库存(" + dto.getSeckillStock() + ")不能超过商品库存(" + item.getStock() + ")");
        }

        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        LocalDateTime rushBeginTime = LocalDateTime.parse(dto.getRushBeginTime(), formatter);
        LocalDateTime rushEndTime = LocalDateTime.parse(dto.getRushEndTime(), formatter);

        // 校验：开抢时间必须在当前时间5分钟之后
        if (rushBeginTime.isBefore(LocalDateTime.now().plusMinutes(5))) {
            throw new BadRequestException("开抢时间请选择5分钟之后");
        }

        if (!rushEndTime.isAfter(rushBeginTime)) {
            throw new BadRequestException("秒杀结束时间必须在开抢时间之后");
        }

        SeckillItem exist = seckillItemMapper.selectById(dto.getItemId());
        SeckillItem seckillItem = exist != null ? exist : new SeckillItem();
        seckillItem.setItemId(dto.getItemId());
        if (dto.getSeckillStock() != null) seckillItem.setSeckillStock(dto.getSeckillStock());
        if (dto.getSeckillPrice() != null) seckillItem.setSeckillPrice(dto.getSeckillPrice());
        if (dto.getMaxPerUser() != null) seckillItem.setMaxPerUser(dto.getMaxPerUser());
        seckillItem.setRushBeginTime(rushBeginTime);
        seckillItem.setRushEndTime(rushEndTime);
        if (exist != null) {
            seckillItemMapper.updateById(seckillItem);
        } else {
            seckillItemMapper.insert(seckillItem);
        }
        // 重新调度秒杀到期自动转普通商品的延迟消息
        scheduleSeckillItemExpire(seckillItem);
        log.info("秒杀商品信息更新成功: itemId={}", dto.getItemId());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void updateSeckillStock(Long itemId, Integer stock) {
        SeckillItem seckillItem = new SeckillItem();
        seckillItem.setItemId(itemId);
        seckillItem.setSeckillStock(stock);
        seckillItemMapper.updateById(seckillItem);
    }

    @Override
    public List<SeckillItemVO> listSeckillItems() {
        // 只查询秒杀商品（item_type=2）的预热信息
        List<SeckillItem> items = seckillItemMapper.selectList(null);
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        return items.stream()
                .map(item -> {
                    ItemDTO itemDTO = itemClient.queryItemById(item.getItemId());
                    if (itemDTO == null || itemDTO.getItemType() == null || itemDTO.getItemType() != 2) {
                        return null; // 过滤掉非秒杀商品
                    }
                    SeckillItemVO vo = new SeckillItemVO();
                    vo.setItemId(item.getItemId());
                    vo.setItemName(itemDTO.getName());
                    vo.setImage(itemDTO.getImage());
                    vo.setPrice(itemDTO.getPrice());
                    vo.setItemType(itemDTO.getItemType());
            vo.setSeckillStock(item.getSeckillStock());
            vo.setSeckillPrice(item.getSeckillPrice());
            vo.setMaxPerUser(item.getMaxPerUser() != null ? item.getMaxPerUser() : 1);
            vo.setRushBeginTime(item.getRushBeginTime() != null ? item.getRushBeginTime().format(formatter) : null);
            vo.setRushEndTime(item.getRushEndTime() != null ? item.getRushEndTime().format(formatter) : null);
            String stockKey = RedisConstants.SECKILL_STOCK_KEY + item.getItemId();
            String redisStock = stringRedisTemplate.opsForValue().get(stockKey);
            if (redisStock != null) {
                vo.setPreheatStatus(1);
                vo.setRedisStock(Integer.parseInt(redisStock));
            } else {
                vo.setPreheatStatus(0);
                vo.setRedisStock(null);
            }
            return vo;
        }).filter(Objects::nonNull).collect(Collectors.toList());
    }

    @Override
    public void preheatStockToRedis(Long itemId) {
        SeckillItem seckillItem = seckillItemMapper.selectById(itemId);
        if (seckillItem == null) {
            throw new BadRequestException("秒杀商品不存在: itemId=" + itemId);
        }
        doPreheatItem(seckillItem);
    }

    @Override
    public int batchPreheatStock(List<Long> itemIds) {
        List<SeckillItem> items;
        if (itemIds == null || itemIds.isEmpty()) {
            items = seckillItemMapper.selectList(null);
        } else {
            items = seckillItemMapper.selectBatchIds(itemIds);
        }
        if (items == null || items.isEmpty()) {
            return 0;
        }
        int count = 0;
        for (SeckillItem item : items) {
            try {
                doPreheatItem(item);
                count++;
            } catch (Exception e) {
                log.error("预热失败: itemId={}", item.getItemId(), e);
            }
        }
        return count;
    }

    @Override
    public PreheatStatusDTO queryPreheatStatus(Long itemId) {
        SeckillItem seckillItem = seckillItemMapper.selectById(itemId);
        PreheatStatusDTO dto = new PreheatStatusDTO();
        dto.setItemId(itemId);
        if (seckillItem != null) {
            dto.setDbStock(seckillItem.getSeckillStock());
        }
        String stockKey = RedisConstants.SECKILL_STOCK_KEY + itemId;
        String redisStock = stringRedisTemplate.opsForValue().get(stockKey);
        if (redisStock != null) {
            dto.setRedisStock(Integer.parseInt(redisStock));
            dto.setPreheated(true);
        } else {
            dto.setRedisStock(null);
            dto.setPreheated(false);
        }
        return dto;
    }

    @Override
    public void clearPreheat(Long itemId) {
        stringRedisTemplate.delete(RedisConstants.SECKILL_STOCK_KEY + itemId);
        stringRedisTemplate.delete(RedisConstants.SECKILL_ORDER_KEY + itemId);
        stringRedisTemplate.delete(RedisConstants.SECKILL_ITEM_KEY + itemId);
        var keys = stringRedisTemplate.keys(RedisConstants.SECKILL_USER_COUNT_KEY + itemId + ":*");
        if (keys != null && !keys.isEmpty()) {
            stringRedisTemplate.delete(keys);
        }
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void convertToNormalItem(Long itemId) {
        // 1. 清除预热
        clearPreheat(itemId);
        // 2. 删除秒杀商品记录
        seckillItemMapper.deleteById(itemId);
        // 3. 更新商品类型为普通商品
        itemClient.updateItemType(itemId, 1);
        log.info("秒杀商品转为普通商品: itemId={}", itemId);
    }

    private void doPreheatItem(SeckillItem item) {
        // 计算TTL：到秒杀结束时间为止
        long ttlSeconds = Duration.between(LocalDateTime.now(), item.getRushEndTime()).getSeconds();
        if (ttlSeconds <= 0) {
            log.warn("秒杀商品已过期，跳过预热: itemId={}, rushEndTime={}", item.getItemId(), item.getRushEndTime());
            return;
        }
        // 1. 缓存秒杀库存（TTL到秒杀结束时间）
        String stockKey = RedisConstants.SECKILL_STOCK_KEY + item.getItemId();
        stringRedisTemplate.opsForValue().set(stockKey, String.valueOf(item.getSeckillStock()), ttlSeconds, TimeUnit.SECONDS);
        // 2. 清除之前的秒杀订单记录
        String orderKey = RedisConstants.SECKILL_ORDER_KEY + item.getItemId();
        stringRedisTemplate.delete(orderKey);
        // 3. 缓存秒杀商品完整信息（秒杀价格、限购、时间等，TTL到秒杀结束时间）
        String itemKey = RedisConstants.SECKILL_ITEM_KEY + item.getItemId();
        stringRedisTemplate.opsForValue().set(itemKey, JSONUtil.toJsonStr(item), ttlSeconds, TimeUnit.SECONDS);
        // 4. 缓存商品详情到与@HotKeyCache相同的key，确保手动预热后浏览也走缓存
        ItemDTO itemDTO = itemClient.queryItemById(item.getItemId());
        if (itemDTO != null) {
            stringRedisTemplate.opsForValue().set(RedisConstants.CACHE_ITEM_KEY + item.getItemId(), JSONUtil.toJsonStr(itemDTO), ttlSeconds, TimeUnit.SECONDS);
        }
        log.info("秒杀商品预热成功: itemId={}, stock={}, ttl={}s, 已缓存商品详情+秒杀配置", item.getItemId(), item.getSeckillStock(), ttlSeconds);
    }

    // ===== Admin: 秒杀优惠券管理（预热管理页面只显示秒杀券） =====

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void createSeckillCoupon(SeckillCouponDTO dto) {
        // 校验优惠券必须是秒杀券
        Coupon coupon = couponMapper.selectById(dto.getCouponId());
        if (coupon == null) {
            throw new BadRequestException("优惠券不存在");
        }
        if (coupon.getCouponType() == null || coupon.getCouponType() != 2) {
            throw new BadRequestException("只有秒杀券才能设置预热信息");
        }

        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        LocalDateTime rushBeginTime = LocalDateTime.parse(dto.getRushBeginTime(), formatter);
        LocalDateTime rushEndTime = LocalDateTime.parse(dto.getRushEndTime(), formatter);

        // 校验：开抢时间必须在当前时间5分钟之后
        if (rushBeginTime.isBefore(LocalDateTime.now().plusMinutes(5))) {
            throw new BadRequestException("开抢时间请选择5分钟之后");
        }

        if (!rushEndTime.isAfter(rushBeginTime)) {
            throw new BadRequestException("秒杀结束时间必须在开抢时间之后");
        }

        SeckillCoupon exist = seckillCouponMapper.selectById(dto.getCouponId());
        SeckillCoupon seckillCoupon = exist != null ? exist : new SeckillCoupon();
        seckillCoupon.setCouponId(dto.getCouponId());
        seckillCoupon.setSeckillStock(dto.getSeckillStock());
        seckillCoupon.setMaxPerUser(1);
        seckillCoupon.setRushBeginTime(rushBeginTime);
        seckillCoupon.setRushEndTime(rushEndTime);
        if (exist != null) {
            seckillCouponMapper.updateById(seckillCoupon);
        } else {
            seckillCouponMapper.insert(seckillCoupon);
        }
        // 调度秒杀优惠券到期自动下架的延迟消息
        scheduleSeckillCouponExpire(seckillCoupon);
        log.info("秒杀优惠券预热设置成功: couponId={}, stock={}, rushBeginTime={}",
                dto.getCouponId(), dto.getSeckillStock(), dto.getRushBeginTime());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public int batchCreateSeckillCoupon(SeckillCouponDTO.BatchCreateRequest request) {
        if (request.getCouponIds() == null || request.getCouponIds().isEmpty()) {
            throw new BadRequestException("请选择至少一个优惠券");
        }
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        LocalDateTime rushBeginTime = LocalDateTime.parse(request.getRushBeginTime(), formatter);
        LocalDateTime rushEndTime = LocalDateTime.parse(request.getRushEndTime(), formatter);

        if (rushBeginTime.isBefore(LocalDateTime.now().plusMinutes(5))) {
            throw new BadRequestException("开抢时间请选择5分钟之后");
        }
        if (!rushEndTime.isAfter(rushBeginTime)) {
            throw new BadRequestException("秒杀结束时间必须在开抢时间之后");
        }

        int count = 0;
        for (Long couponId : request.getCouponIds()) {
            try {
                // 1. 将优惠券类型设为秒杀券(couponType=2)
                Coupon coupon = couponMapper.selectById(couponId);
                if (coupon == null) {
                    log.warn("优惠券不存在: couponId={}", couponId);
                    continue;
                }
                if (coupon.getCouponType() == null || coupon.getCouponType() != 2) {
                    coupon.setCouponType(2);
                    couponMapper.updateById(coupon);
                }
                // 2. 创建/更新秒杀优惠券记录
                SeckillCoupon exist = seckillCouponMapper.selectById(couponId);
                SeckillCoupon seckillCoupon = exist != null ? exist : new SeckillCoupon();
                seckillCoupon.setCouponId(couponId);
                seckillCoupon.setSeckillStock(request.getSeckillStock());
                seckillCoupon.setMaxPerUser(1);
                seckillCoupon.setRushBeginTime(rushBeginTime);
                seckillCoupon.setRushEndTime(rushEndTime);
                if (exist != null) {
                    seckillCouponMapper.updateById(seckillCoupon);
                } else {
                    seckillCouponMapper.insert(seckillCoupon);
                }
                scheduleSeckillCouponExpire(seckillCoupon);
                count++;
            } catch (Exception e) {
                log.error("批量设置秒杀优惠券失败: couponId={}", couponId, e);
            }
        }
        log.info("批量设置秒杀优惠券完成: 成功{}个, 共{}个", count, request.getCouponIds().size());
        return count;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void updateSeckillCouponStock(Long couponId, Integer stock) {
        SeckillCoupon seckillCoupon = seckillCouponMapper.selectById(couponId);
        if (seckillCoupon == null) {
            throw new BadRequestException("秒杀优惠券预热信息不存在");
        }
        seckillCoupon.setSeckillStock(stock);
        seckillCouponMapper.updateById(seckillCoupon);
    }

    @Override
    public List<SeckillCouponVO> listSeckillCoupons() {
        // 只查询秒杀券（coupon_type=2）的预热信息
        List<SeckillCoupon> coupons = seckillCouponMapper.selectList(null);
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        return coupons.stream().map(c -> {
            Coupon coupon = couponMapper.selectById(c.getCouponId());
            if (coupon == null || coupon.getCouponType() == null || coupon.getCouponType() != 2) {
                return null; // 过滤掉非秒杀券
            }
            SeckillCouponVO vo = new SeckillCouponVO();
            vo.setCouponId(c.getCouponId());
            vo.setCouponName(coupon.getName());
            vo.setType(coupon.getType());
            vo.setDiscountValue(coupon.getDiscountValue());
            vo.setPurchasePrice(coupon.getPurchasePrice());
            vo.setSeckillStock(c.getSeckillStock());
            vo.setMaxPerUser(c.getMaxPerUser() != null ? c.getMaxPerUser() : 1);
            vo.setRushBeginTime(c.getRushBeginTime() != null ? c.getRushBeginTime().format(formatter) : null);
            vo.setRushEndTime(c.getRushEndTime() != null ? c.getRushEndTime().format(formatter) : null);
            String stockKey = RedisConstants.SECKILL_COUPON_STOCK_KEY + c.getCouponId();
            String redisStock = stringRedisTemplate.opsForValue().get(stockKey);
            if (redisStock != null) {
                vo.setPreheatStatus(1);
                vo.setRedisStock(Integer.parseInt(redisStock));
            } else {
                vo.setPreheatStatus(0);
                vo.setRedisStock(null);
            }
            return vo;
        }).filter(Objects::nonNull).collect(Collectors.toList());
    }

    @Override
    public void preheatCouponStockToRedis(Long couponId) {
        SeckillCoupon seckillCoupon = seckillCouponMapper.selectById(couponId);
        if (seckillCoupon == null) {
            throw new BadRequestException("秒杀优惠券预热信息不存在: couponId=" + couponId);
        }
        doPreheatCoupon(seckillCoupon);
    }

    @Override
    public int batchPreheatCouponStock(List<Long> couponIds) {
        List<SeckillCoupon> coupons;
        if (couponIds == null || couponIds.isEmpty()) {
            coupons = seckillCouponMapper.selectList(null);
        } else {
            coupons = seckillCouponMapper.selectBatchIds(couponIds);
        }
        if (coupons == null || coupons.isEmpty()) {
            return 0;
        }
        int count = 0;
        for (SeckillCoupon c : coupons) {
            try {
                doPreheatCoupon(c);
                count++;
            } catch (Exception e) {
                log.error("预热失败: couponId={}", c.getCouponId(), e);
            }
        }
        return count;
    }

    @Override
    public void clearCouponPreheat(Long couponId) {
        stringRedisTemplate.delete(RedisConstants.SECKILL_COUPON_STOCK_KEY + couponId);
        stringRedisTemplate.delete(RedisConstants.SECKILL_COUPON_ORDER_KEY + couponId);
        stringRedisTemplate.delete(RedisConstants.SECKILL_COUPON_KEY + couponId);
        stringRedisTemplate.delete("cache:coupon:" + couponId);
        var keys = stringRedisTemplate.keys(RedisConstants.SECKILL_COUPON_USER_COUNT_KEY + couponId + ":*");
        if (keys != null && !keys.isEmpty()) {
            stringRedisTemplate.delete(keys);
        }
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void convertToNormalCoupon(Long couponId) {
        // 1. 清除预热
        clearCouponPreheat(couponId);
        // 2. 删除秒杀优惠券记录
        seckillCouponMapper.deleteById(couponId);
        // 3. 更新优惠券类型为普通优惠券
        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon != null) {
            coupon.setCouponType(1);
            couponMapper.updateById(coupon);
        }
        log.info("秒杀优惠券转为普通优惠券: couponId={}", couponId);
    }

    private void doPreheatCoupon(SeckillCoupon coupon) {
        // 计算TTL：到秒杀结束时间为止
        long ttlSeconds = Duration.between(LocalDateTime.now(), coupon.getRushEndTime()).getSeconds();
        if (ttlSeconds <= 0) {
            log.warn("秒杀优惠券已过期，跳过预热: couponId={}, rushEndTime={}", coupon.getCouponId(), coupon.getRushEndTime());
            return;
        }
        // 1. 缓存秒杀优惠券库存（TTL到秒杀结束时间）
        String stockKey = RedisConstants.SECKILL_COUPON_STOCK_KEY + coupon.getCouponId();
        stringRedisTemplate.opsForValue().set(stockKey, String.valueOf(coupon.getSeckillStock()), ttlSeconds, TimeUnit.SECONDS);
        // 2. 清除之前的秒杀优惠券订单记录
        String orderKey = RedisConstants.SECKILL_COUPON_ORDER_KEY + coupon.getCouponId();
        stringRedisTemplate.delete(orderKey);
        // 3. 缓存秒杀优惠券完整信息（限购、时间等，TTL到秒杀结束时间）
        String couponKey = RedisConstants.SECKILL_COUPON_KEY + coupon.getCouponId();
        stringRedisTemplate.opsForValue().set(couponKey, JSONUtil.toJsonStr(coupon), ttlSeconds, TimeUnit.SECONDS);
        // 4. 缓存优惠券详情到与getCouponFromCache相同的key，确保手动预热后下单也走缓存
        Coupon couponInfo = couponMapper.selectById(coupon.getCouponId());
        if (couponInfo != null) {
            stringRedisTemplate.opsForValue().set("cache:coupon:" + coupon.getCouponId(), JSONUtil.toJsonStr(couponInfo), ttlSeconds, TimeUnit.SECONDS);
        }
        log.info("秒杀优惠券预热成功: couponId={}, stock={}, ttl={}s, 已缓存优惠券详情+秒杀配置", coupon.getCouponId(), coupon.getSeckillStock(), ttlSeconds);
    }

    /**
     * 从缓存获取秒杀商品信息，缓存未命中则查库并回填
     */
    private SeckillItem getSeckillItemFromCache(Long itemId) {
        String itemKey = RedisConstants.SECKILL_ITEM_KEY + itemId;
        String json = stringRedisTemplate.opsForValue().get(itemKey);
        if (cn.hutool.core.util.StrUtil.isNotBlank(json)) {
            return JSONUtil.toBean(json, SeckillItem.class);
        }
        // 缓存未命中，查库
        SeckillItem seckillItem = seckillItemMapper.selectById(itemId);
        if (seckillItem != null) {
            stringRedisTemplate.opsForValue().set(itemKey, JSONUtil.toJsonStr(seckillItem));
        }
        return seckillItem;
    }

    /**
     * 从缓存获取秒杀优惠券信息，缓存未命中则查库并回填
     */
    private SeckillCoupon getSeckillCouponFromCache(Long couponId) {
        String couponKey = RedisConstants.SECKILL_COUPON_KEY + couponId;
        String json = stringRedisTemplate.opsForValue().get(couponKey);
        if (cn.hutool.core.util.StrUtil.isNotBlank(json)) {
            return JSONUtil.toBean(json, SeckillCoupon.class);
        }
        // 缓存未命中，查库
        SeckillCoupon seckillCoupon = seckillCouponMapper.selectById(couponId);
        if (seckillCoupon != null) {
            stringRedisTemplate.opsForValue().set(couponKey, JSONUtil.toJsonStr(seckillCoupon));
        }
        return seckillCoupon;
    }

    /**
     * 从缓存获取优惠券信息（用于秒杀券下单时判断免费/付费），缓存未命中则查库并回填
     */
    private Coupon getCouponFromCache(Long couponId) {
        String key = "cache:coupon:" + couponId;
        String json = stringRedisTemplate.opsForValue().get(key);
        if (cn.hutool.core.util.StrUtil.isNotBlank(json)) {
            return JSONUtil.toBean(json, Coupon.class);
        }
        // 缓存未命中，查库
        Coupon coupon = couponMapper.selectById(couponId);
        if (coupon != null) {
            stringRedisTemplate.opsForValue().set(key, JSONUtil.toJsonStr(coupon));
        }
        return coupon;
    }

    /**
     * 调度秒杀商品到期自动转普通商品的延迟消息
     */
    private void scheduleSeckillItemExpire(SeckillItem seckillItem) {
        if (seckillItem.getRushEndTime() == null) {
            return;
        }
        LocalDateTime now = LocalDateTime.now();
        long delayMs = java.time.Duration.between(now, seckillItem.getRushEndTime()).toMillis();
        if (delayMs <= 0) {
            // 已过期，立即处理
            handleSeckillItemExpire(seckillItem.getItemId());
            return;
        }
        int delay = (int) Math.min(delayMs, Integer.MAX_VALUE);
        try {
            rabbitMqHelper.sendDelayMessageWithConfirm(
                    MqConstants.SECKILL_ITEM_EXPIRE_DELAY_EXCHANGE,
                    MqConstants.SECKILL_ITEM_EXPIRE_DELAY_KEY,
                    seckillItem.getItemId(),
                    delay,
                    3);
            log.info("秒杀商品到期延迟消息已发送: itemId={}, delayMs={}", seckillItem.getItemId(), delayMs);
        } catch (Exception e) {
            log.error("秒杀商品到期延迟消息发送失败: itemId={}", seckillItem.getItemId(), e);
        }
    }

    /**
     * 调度秒杀优惠券到期自动下架的延迟消息
     */
    private void scheduleSeckillCouponExpire(SeckillCoupon seckillCoupon) {
        if (seckillCoupon.getRushEndTime() == null) {
            return;
        }
        LocalDateTime now = LocalDateTime.now();
        long delayMs = java.time.Duration.between(now, seckillCoupon.getRushEndTime()).toMillis();
        if (delayMs <= 0) {
            // 已过期，立即处理
            handleSeckillCouponExpire(seckillCoupon.getCouponId());
            return;
        }
        int delay = (int) Math.min(delayMs, Integer.MAX_VALUE);
        try {
            rabbitMqHelper.sendDelayMessageWithConfirm(
                    MqConstants.SECKILL_COUPON_EXPIRE_DELAY_EXCHANGE,
                    MqConstants.SECKILL_COUPON_EXPIRE_DELAY_KEY,
                    seckillCoupon.getCouponId(),
                    delay,
                    3);
            log.info("秒杀优惠券到期延迟消息已发送: couponId={}, delayMs={}", seckillCoupon.getCouponId(), delayMs);
        } catch (Exception e) {
            log.error("秒杀优惠券到期延迟消息发送失败: couponId={}", seckillCoupon.getCouponId(), e);
        }
    }

    /**
     * 处理秒杀商品到期：转为普通商品，恢复原价
     */
    @Override
    public void handleSeckillItemExpire(Long itemId) {
        try {
            // 1. 将商品类型从秒杀(2)改为普通(1)
            itemClient.updateItemType(itemId, 1);
            // 2. 清除Redis预热数据
            clearPreheat(itemId);
            // 3. 删除秒杀商品记录
            seckillItemMapper.deleteById(itemId);
            log.info("秒杀商品到期，已自动转为普通商品: itemId={}", itemId);
        } catch (Exception e) {
            log.error("秒杀商品到期自动转普通商品失败: itemId={}", itemId, e);
        }
    }

    /**
     * 处理秒杀优惠券到期：自动下架
     */
    @Override
    public void handleSeckillCouponExpire(Long couponId) {
        try {
            // 1. 下架优惠券
            Coupon coupon = couponMapper.selectById(couponId);
            if (coupon != null && coupon.getStatus() == 1) {
                coupon.setStatus(0);
                couponMapper.updateById(coupon);
            }
            // 2. 清除Redis预热数据
            clearCouponPreheat(couponId);
            // 3. 删除秒杀优惠券记录
            seckillCouponMapper.deleteById(couponId);
            log.info("秒杀优惠券到期，已自动下架: couponId={}", couponId);
        } catch (Exception e) {
            log.error("秒杀优惠券到期自动下架失败: couponId={}", couponId, e);
        }
    }
}
