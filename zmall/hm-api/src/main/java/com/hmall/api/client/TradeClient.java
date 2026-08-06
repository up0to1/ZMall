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

    @PutMapping("/orders/{orderId}/pay")
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

    /**
     * 服务间调用：查询用户所有已完成订单中的 item_id 去重列表
     * 用于 US-AT-17 排除已购买的商品
     */
    @GetMapping("/orders/user/item-ids")
    List<Long> queryUserOrderItemIds(@RequestParam("userId") Long userId);

    /**
     * 服务间调用：商品被物理删除时，标记所有引用该商品的 order_detail 快照
     * <p>将 order_detail.name 改为 "【原商品名】商品已删除"，image 改为占位图。
     * <p>路径 /orders/internal/item-deleted 已在网关层禁止外部访问。
     */
    @PostMapping("/orders/internal/item-deleted")
    void markItemDeletedInOrders(@RequestBody ItemDeletedMessage msg);
}
