package com.hmall.trade.service;

import com.hmall.api.dto.PreheatStatusDTO;
import com.hmall.api.dto.SeckillCouponDTO;
import com.hmall.api.dto.SeckillItemDTO;
import com.hmall.api.vo.SeckillCouponVO;
import com.hmall.api.vo.SeckillItemVO;
import com.hmall.trade.domain.dto.SeckillResult;

import java.util.List;

public interface ISeckillService {

    // ===== 前台用户接口 =====

    SeckillResult seckillItem(Long itemId, Long userId, Long couponId);

    SeckillResult querySeckillResult(Long itemId, Long userId);

    SeckillResult seckillCoupon(Long couponId, Long userId);

    SeckillResult querySeckillCouponResult(Long couponId, Long userId);

    // ===== Admin: 秒杀商品管理 =====

    void createSeckill(SeckillItemDTO dto);

    int batchCreateSeckill(SeckillItemDTO.BatchCreateRequest request);

    void updateSeckill(SeckillItemDTO dto);

    void updateSeckillStock(Long itemId, Integer stock);

    List<SeckillItemVO> listSeckillItems();

    void preheatStockToRedis(Long itemId);

    int batchPreheatStock(List<Long> itemIds);

    PreheatStatusDTO queryPreheatStatus(Long itemId);

    void clearPreheat(Long itemId);

    void convertToNormalItem(Long itemId);

    // ===== Admin: 秒杀优惠券管理 =====

    void createSeckillCoupon(SeckillCouponDTO dto);

    int batchCreateSeckillCoupon(SeckillCouponDTO.BatchCreateRequest request);

    void updateSeckillCouponStock(Long couponId, Integer stock);

    List<SeckillCouponVO> listSeckillCoupons();

    void preheatCouponStockToRedis(Long couponId);

    int batchPreheatCouponStock(List<Long> couponIds);

    void clearCouponPreheat(Long couponId);

    void convertToNormalCoupon(Long couponId);

    // ===== 自动到期处理 =====

    void handleSeckillItemExpire(Long itemId);

    void handleSeckillCouponExpire(Long couponId);
}
