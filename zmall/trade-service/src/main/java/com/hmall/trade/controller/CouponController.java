package com.hmall.trade.controller;

import com.hmall.common.domain.PageDTO;
import com.hmall.api.dto.CouponDTO;
import com.hmall.api.dto.CouponStatsDTO;
import com.hmall.api.vo.CouponVO;
import com.hmall.common.utils.UserContext;
import com.hmall.trade.service.ICouponService;
import com.hmall.trade.service.IOrderService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Api(tags = "优惠券管理接口")
@RestController
@RequestMapping("/coupons")
@RequiredArgsConstructor
public class CouponController {

    private final ICouponService couponService;
    private final IOrderService orderService;

    // ========== 后台管理接口 ==========

    @ApiOperation("创建优惠券")
    @PostMapping("/admin")
    public void createCoupon(@RequestBody CouponDTO dto) {
        couponService.createCoupon(dto);
    }

    @ApiOperation("更新优惠券")
    @PutMapping("/admin/{id}")
    public void updateCoupon(@PathVariable("id") Long id, @RequestBody CouponDTO dto) {
        couponService.updateCoupon(id, dto);
    }

    @ApiOperation("查询优惠券列表")
    @GetMapping("/admin/page")
    public PageDTO<CouponVO> queryCouponPage(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size,
            @RequestParam(value = "status", required = false) Integer status,
            @RequestParam(value = "couponType", required = false) Integer couponType) {
        return couponService.queryCouponPage(page, size, status, couponType);
    }

    @ApiOperation("上架/下架优惠券")
    @PutMapping("/admin/{id}/status/{status}")
    public void updateCouponStatus(@PathVariable("id") Long id, @PathVariable("status") Integer status) {
        couponService.updateCouponStatus(id, status);
    }

    @ApiOperation("更新优惠券类别（普通/秒杀）")
    @PutMapping("/admin/{id}/couponType/{couponType}")
    public void updateCouponType(@PathVariable("id") Long id, @PathVariable("couponType") Integer couponType) {
        couponService.updateCouponType(id, couponType);
    }

    @ApiOperation("设为秒杀优惠券（含秒杀信息）")
    @PutMapping("/admin/{id}/seckill")
    public void setSeckillCoupon(@PathVariable("id") Long id, @RequestBody CouponDTO dto) {
        couponService.setSeckillCoupon(id, dto);
    }

    @ApiOperation("查询优惠券详情（含秒杀信息）")
    @GetMapping("/admin/{id}")
    public CouponVO getCouponDetail(@PathVariable("id") Long id) {
        return couponService.getCouponDetail(id);
    }

    @ApiOperation("删除优惠券")
    @DeleteMapping("/admin/{id}")
    public void deleteCoupon(@PathVariable("id") Long id) {
        couponService.deleteCoupon(id);
    }

    @ApiOperation("优惠券统计")
    @GetMapping("/admin/stats")
    public CouponStatsDTO getCouponStats() {
        return couponService.getCouponStats();
    }

    // ========== 前台用户接口 ==========

    @ApiOperation("免费领取优惠券")
    @PostMapping("/{id}/receive")
    public void receiveCoupon(@PathVariable("id") Long couponId) {
        Long userId = UserContext.getUser();
        couponService.receiveCoupon(couponId, userId);
    }

    @ApiOperation("付费购买优惠券")
    @PostMapping("/{id}/purchase")
    public Long purchaseCoupon(@PathVariable("id") Long couponId,
                               @RequestParam(value = "paymentType", defaultValue = "3") Integer paymentType) {
        Long userId = UserContext.getUser();
        // 先校验优惠券可购买
        couponService.purchaseCoupon(couponId, userId, paymentType);
        // 创建优惠券购买订单并返回订单ID
        return orderService.createCouponOrder(couponId, userId, paymentType);
    }

    @ApiOperation("使用优惠券")
    @PostMapping("/{id}/use")
    public void useCoupon(@PathVariable("id") Long couponId,
                          @RequestParam("orderId") Long orderId) {
        Long userId = UserContext.getUser();
        couponService.useCoupon(couponId, userId, orderId);
    }

    @ApiOperation("前台-查询可领取的优惠券列表")
    @GetMapping("/available")
    public PageDTO<CouponVO> queryAvailableCoupons(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size,
            @RequestParam(value = "couponType", required = false) Integer couponType) {
        return couponService.queryAvailableCoupons(page, size, couponType);
    }

    @ApiOperation("前台-查询商品可用优惠券列表")
    @GetMapping("/item/{itemId}")
    public List<CouponVO> queryItemCoupons(@PathVariable("itemId") Long itemId) {
        return couponService.queryItemCoupons(itemId);
    }

    @ApiOperation("前台-查询当前用户可用的优惠券（未使用）")
    @GetMapping("/user/available")
    public List<CouponVO> queryUserAvailableCoupons() {
        Long userId = UserContext.getUser();
        return couponService.queryUserAvailableCoupons(userId);
    }

    @ApiOperation("前台-查询当前用户每张优惠券的已领取数量")
    @GetMapping("/user/received-count")
    public java.util.Map<Long, Long> queryUserReceivedCount() {
        Long userId = UserContext.getUser();
        return couponService.queryUserReceivedCount(userId);
    }
}
