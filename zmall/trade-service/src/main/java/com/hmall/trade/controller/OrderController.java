package com.hmall.trade.controller;

import com.hmall.api.vo.MerchantOrderVO;
import com.hmall.common.domain.PageDTO;
import com.hmall.api.dto.OrderStatsDTO;
import com.hmall.api.dto.SalesTrendDTO;
import com.hmall.api.dto.TopItemDTO;
import com.hmall.common.utils.UserContext;
import com.hmall.trade.domain.dto.OrderFormDTO;
import com.hmall.trade.domain.po.Order;
import com.hmall.trade.service.IOrderService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Api(tags = "订单管理接口")
@RestController
@RequestMapping("/orders")
@RequiredArgsConstructor
public class OrderController {

    private final IOrderService orderService;

    @ApiOperation("创建商品订单")
    @PostMapping
    public Long createOrder(@RequestBody OrderFormDTO orderFormDTO) {
        return orderService.createOrder(orderFormDTO);
    }

    @ApiOperation("查询订单详情")
    @GetMapping("/{id}")
    public MerchantOrderVO queryOrderById(@PathVariable("id") Long orderId) {
        return orderService.queryOrderById(orderId);
    }

    @ApiOperation("模拟支付成功")
    @PutMapping("/{id}/pay")
    public void markOrderPaySuccess(@PathVariable("id") Long orderId) {
        orderService.markOrderPaySuccess(orderId);
    }

    @ApiOperation("取消订单")
    @PutMapping("/{id}/cancel")
    public void cancelOrder(@PathVariable("id") Long orderId) {
        orderService.cancelOrder(orderId);
    }

    @ApiOperation("用户申请退款（待发货，直接成功）")
    @PutMapping("/{id}/refund")
    public void applyRefund(@PathVariable("id") Long orderId) {
        orderService.applyRefund(orderId);
    }

    @ApiOperation("用户申请退货（已到货，需商家审核）")
    @PutMapping("/{id}/return")
    public void applyReturn(@PathVariable("id") Long orderId) {
        orderService.applyReturn(orderId);
    }

    @ApiOperation("用户取消退货（审核前可取消）")
    @PutMapping("/{id}/cancel-return")
    public void cancelReturn(@PathVariable("id") Long orderId) {
        orderService.cancelReturn(orderId);
    }

    @ApiOperation("用户确认收货")
    @PutMapping("/{id}/confirm")
    public void confirmReceive(@PathVariable("id") Long orderId) {
        orderService.confirmReceive(orderId);
    }

    @ApiOperation("用户评价订单后更新状态")
    @PutMapping("/{id}/comment")
    public void commentOrder(@PathVariable("id") Long orderId) {
        orderService.commentOrder(orderId);
    }

    @ApiOperation("前台-用户订单列表")
    @GetMapping("/user/page")
    public PageDTO<MerchantOrderVO> queryUserOrderPage(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size,
            @RequestParam(value = "status", required = false) Integer status) {
        Long userId = UserContext.getUser();
        return orderService.queryUserOrderPage(userId, page, size, status);
    }

    @ApiOperation("商家后台-订单分页查询")
    @GetMapping("/merchant/page")
    public PageDTO<MerchantOrderVO> queryMerchantOrderPage(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size,
            @RequestParam(value = "status", required = false) Integer status,
            @RequestParam(value = "beginTime", required = false) String beginTime,
            @RequestParam(value = "endTime", required = false) String endTime) {
        return orderService.queryMerchantOrderPage(page, size, status, beginTime, endTime);
    }

    @ApiOperation("商家后台-订单详情")
    @GetMapping("/merchant/{id}")
    public MerchantOrderVO queryMerchantOrderDetail(@PathVariable("id") Long orderId) {
        return orderService.queryMerchantOrderDetail(orderId);
    }

    @ApiOperation("商家后台-发货（模拟，点击后立即到货）")
    @PutMapping("/merchant/{id}/ship")
    public void shipOrder(@PathVariable("id") Long orderId) {
        orderService.shipOrder(orderId);
    }

    @ApiOperation("商家后台-退款（同意退货，立刻退钱）")
    @PutMapping("/merchant/{id}/refund")
    public void refundOrder(@PathVariable("id") Long orderId) {
        orderService.refundOrder(orderId);
    }

    @ApiOperation("商家后台-审核通过退货")
    @PutMapping("/merchant/{id}/approve-return")
    public void approveReturn(@PathVariable("id") Long orderId) {
        orderService.approveReturn(orderId);
    }

    @ApiOperation("商家后台-拒绝退货")
    @PutMapping("/merchant/{id}/reject-return")
    public void rejectReturn(@PathVariable("id") Long orderId) {
        orderService.rejectReturn(orderId);
    }

    @ApiOperation("商家后台-订单统计")
    @GetMapping("/merchant/stats")
    public OrderStatsDTO getMerchantOrderStats() {
        return orderService.getMerchantOrderStats();
    }

    @ApiOperation("商家后台-销售趋势")
    @GetMapping("/merchant/sales-trend")
    public List<SalesTrendDTO> getSalesTrend(
            @RequestParam(value = "days", defaultValue = "7") Integer days) {
        return orderService.getSalesTrend(days);
    }

    @ApiOperation("商家后台-热销商品")
    @GetMapping("/merchant/top-items")
    public List<TopItemDTO> getTopItems(
            @RequestParam(value = "limit", defaultValue = "10") Integer limit) {
        return orderService.getTopItems(limit);
    }
}
