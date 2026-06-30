package com.hmall.trade.controller;

import com.hmall.api.dto.SeckillCouponDTO;
import com.hmall.api.dto.SeckillItemDTO;
import com.hmall.api.vo.SeckillCouponVO;
import com.hmall.api.vo.SeckillItemVO;
import com.hmall.common.utils.UserContext;
import com.hmall.trade.domain.dto.SeckillResult;
import com.hmall.trade.service.ISeckillService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Api(tags = "秒杀相关接口")
@RestController
@RequestMapping("/seckill")
@RequiredArgsConstructor
public class SeckillController {

    private final ISeckillService seckillService;

    // ===== 前台用户接口 =====

    @ApiOperation("秒杀下单")
    @PostMapping("/{itemId}")
    public SeckillResult seckillItem(@PathVariable("itemId") Long itemId,
                                     @RequestParam(value = "couponId", required = false) Long couponId) {
        Long userId = UserContext.getUser();
        return seckillService.seckillItem(itemId, userId, couponId);
    }

    @ApiOperation("查询秒杀结果")
    @GetMapping("/result/{itemId}")
    public SeckillResult querySeckillResult(@PathVariable("itemId") Long itemId) {
        Long userId = UserContext.getUser();
        return seckillService.querySeckillResult(itemId, userId);
    }

    @ApiOperation("秒杀优惠券")
    @PostMapping("/coupon/{couponId}")
    public SeckillResult seckillCoupon(@PathVariable("couponId") Long couponId) {
        Long userId = UserContext.getUser();
        return seckillService.seckillCoupon(couponId, userId);
    }

    @ApiOperation("查询秒杀优惠券结果")
    @GetMapping("/coupon/result/{couponId}")
    public SeckillResult querySeckillCouponResult(@PathVariable("couponId") Long couponId) {
        Long userId = UserContext.getUser();
        return seckillService.querySeckillCouponResult(couponId, userId);
    }

    @ApiOperation("前台-查询秒杀商品列表")
    @GetMapping("/items")
    public List<SeckillItemVO> listSeckillItemsForUser() {
        return seckillService.listSeckillItems();
    }

    @ApiOperation("前台-查询秒杀优惠券列表")
    @GetMapping("/coupons")
    public List<SeckillCouponVO> listSeckillCouponsForUser() {
        return seckillService.listSeckillCoupons();
    }

    // ===== Admin: 秒杀商品管理 =====

    @ApiOperation("创建秒杀商品活动")
    @PostMapping("/admin/item")
    public void createSeckill(@RequestBody SeckillItemDTO dto) {
        seckillService.createSeckill(dto);
    }

    @ApiOperation("批量设置秒杀商品")
    @PostMapping("/admin/item/batch")
    public int batchCreateSeckill(@RequestBody SeckillItemDTO.BatchCreateRequest request) {
        return seckillService.batchCreateSeckill(request);
    }

    @ApiOperation("更新秒杀商品活动（含秒杀信息）")
    @PutMapping("/admin/item")
    public void updateSeckill(@RequestBody SeckillItemDTO dto) {
        seckillService.updateSeckill(dto);
    }

    @ApiOperation("更新秒杀商品库存")
    @PutMapping("/admin/item/{itemId}/stock/{stock}")
    public void updateSeckillStock(@PathVariable Long itemId, @PathVariable Integer stock) {
        seckillService.updateSeckillStock(itemId, stock);
    }

    @ApiOperation("查询秒杀商品列表")
    @GetMapping("/admin/item/list")
    public List<SeckillItemVO> listSeckillItems() {
        return seckillService.listSeckillItems();
    }

    @ApiOperation("预热秒杀商品库存")
    @PostMapping("/admin/item/preheat/{itemId}")
    public void preheatStockToRedis(@PathVariable Long itemId) {
        seckillService.preheatStockToRedis(itemId);
    }

    @ApiOperation("批量预热秒杀商品库存")
    @PostMapping("/admin/item/preheat/batch")
    public int batchPreheatStock(@RequestBody(required = false) List<Long> itemIds) {
        return seckillService.batchPreheatStock(itemIds);
    }

    @ApiOperation("清除秒杀商品预热")
    @DeleteMapping("/admin/item/preheat/{itemId}")
    public void clearPreheat(@PathVariable Long itemId) {
        seckillService.clearPreheat(itemId);
    }

    @ApiOperation("秒杀商品转为普通商品")
    @PutMapping("/admin/item/convert/{itemId}")
    public void convertToNormalItem(@PathVariable Long itemId) {
        seckillService.convertToNormalItem(itemId);
    }

    // ===== Admin: 秒杀优惠券管理 =====

    @ApiOperation("创建秒杀优惠券活动")
    @PostMapping("/admin/coupon")
    public void createSeckillCoupon(@RequestBody SeckillCouponDTO dto) {
        seckillService.createSeckillCoupon(dto);
    }

    @ApiOperation("批量设置秒杀优惠券")
    @PostMapping("/admin/coupon/batch")
    public int batchCreateSeckillCoupon(@RequestBody SeckillCouponDTO.BatchCreateRequest request) {
        return seckillService.batchCreateSeckillCoupon(request);
    }

    @ApiOperation("更新秒杀优惠券库存")
    @PutMapping("/admin/coupon/{couponId}/stock/{stock}")
    public void updateSeckillCouponStock(@PathVariable Long couponId, @PathVariable Integer stock) {
        seckillService.updateSeckillCouponStock(couponId, stock);
    }

    @ApiOperation("查询秒杀优惠券列表")
    @GetMapping("/admin/coupon/list")
    public List<SeckillCouponVO> listSeckillCoupons() {
        return seckillService.listSeckillCoupons();
    }

    @ApiOperation("预热秒杀优惠券库存")
    @PostMapping("/admin/coupon/preheat/{couponId}")
    public void preheatCouponStockToRedis(@PathVariable Long couponId) {
        seckillService.preheatCouponStockToRedis(couponId);
    }

    @ApiOperation("批量预热秒杀优惠券库存")
    @PostMapping("/admin/coupon/preheat/batch")
    public int batchPreheatCouponStock(@RequestBody(required = false) List<Long> couponIds) {
        return seckillService.batchPreheatCouponStock(couponIds);
    }

    @ApiOperation("清除秒杀优惠券预热")
    @DeleteMapping("/admin/coupon/preheat/{couponId}")
    public void clearCouponPreheat(@PathVariable Long couponId) {
        seckillService.clearCouponPreheat(couponId);
    }

    @ApiOperation("秒杀优惠券转为普通优惠券")
    @PutMapping("/admin/coupon/convert/{couponId}")
    public void convertToNormalCoupon(@PathVariable Long couponId) {
        seckillService.convertToNormalCoupon(couponId);
    }
}
