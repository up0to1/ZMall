package com.hmall.api.client;


import com.hmall.common.domain.PageDTO;
import com.hmall.api.client.fallback.TradeClientFallbackFactory;
import com.hmall.api.dto.*;
import com.hmall.api.vo.CouponVO;
import com.hmall.api.vo.MerchantOrderVO;
import com.hmall.api.vo.SeckillItemVO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@FeignClient(value = "trade-service", fallbackFactory = TradeClientFallbackFactory.class)
public interface TradeClient {

    @PutMapping("/orders/{orderId}")
    void markOrderPaySuccess(@PathVariable("orderId") Long orderId);

    @GetMapping("/orders/merchant/page")
    PageDTO<MerchantOrderVO> queryMerchantOrderPage(
            @RequestParam("page") int page,
            @RequestParam("size") int size,
            @RequestParam(value = "status", required = false) Integer status,
            @RequestParam(value = "beginTime", required = false) String beginTime,
            @RequestParam(value = "endTime", required = false) String endTime);

    @GetMapping("/orders/merchant/{id}")
    MerchantOrderVO queryMerchantOrderDetail(@PathVariable("id") Long orderId);

    @PutMapping("/orders/merchant/{id}/ship")
    void shipOrder(@PathVariable("id") Long orderId);

    @PutMapping("/orders/merchant/{id}/refund")
    void refundOrder(@PathVariable("id") Long orderId);

    @GetMapping("/orders/merchant/stats")
    OrderStatsDTO getMerchantOrderStats();

    @GetMapping("/orders/merchant/sales-trend")
    List<SalesTrendDTO> getSalesTrend(@RequestParam(value = "days", defaultValue = "7") Integer days);

    @GetMapping("/orders/merchant/top-items")
    List<TopItemDTO> getTopItems(@RequestParam(value = "limit", defaultValue = "10") Integer limit);

    // ========== Coupon 优惠券 ==========

    @PostMapping("/coupons/admin")
    void createCoupon(@RequestBody CouponDTO dto);

    @PutMapping("/coupons/admin/{id}")
    void updateCoupon(@PathVariable("id") Long id, @RequestBody CouponDTO dto);

    @GetMapping("/coupons/admin/page")
    PageDTO<CouponVO> queryCouponPage(
            @RequestParam("page") int page,
            @RequestParam("size") int size);

    @PutMapping("/coupons/admin/{id}/status/{status}")
    void updateCouponStatus(@PathVariable("id") Long id, @PathVariable("status") Integer status);

    @GetMapping("/coupons/admin/stats")
    CouponStatsDTO getCouponStats();

    // ========== Seckill 秒杀商品 ==========

    @PostMapping("/seckill/admin/item")
    void createSeckill(@RequestBody SeckillItemDTO dto);

    @GetMapping("/seckill/admin/item/list")
    List<SeckillItemVO> listSeckillItems();

    @PutMapping("/seckill/admin/item/{itemId}/stock/{stock}")
    void updateSeckillStock(@PathVariable("itemId") Long itemId,
                            @PathVariable("stock") Integer stock);

    @PostMapping("/seckill/admin/item/preheat/{itemId}")
    void preheatStockToRedis(@PathVariable("itemId") Long itemId);

    @PostMapping("/seckill/admin/item/preheat/batch")
    int batchPreheatStock(@RequestBody List<Long> itemIds);

    @DeleteMapping("/seckill/admin/item/preheat/{itemId}")
    void clearPreheat(@PathVariable("itemId") Long itemId);
}
