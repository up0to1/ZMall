package com.hmall.trade.service;

import com.hmall.api.vo.MerchantOrderVO;
import com.hmall.common.domain.PageDTO;
import com.hmall.api.dto.OrderStatsDTO;
import com.hmall.api.dto.SalesTrendDTO;
import com.hmall.api.dto.TopItemDTO;
import com.hmall.trade.domain.dto.OrderFormDTO;
import com.hmall.trade.domain.po.Order;

import java.util.List;

public interface IOrderService {

    Long createOrder(OrderFormDTO orderFormDTO);

    MerchantOrderVO queryOrderById(Long orderId);

    Long createCouponOrder(Long couponId, Long userId, Integer paymentType);

    Long createSeckillOrder(Long orderId, Long userId, Long itemId, int num, int seckillPrice, Long couponId);

    void markOrderPaySuccess(Long orderId);

    void cancelOrder(Long orderId);

    PageDTO<MerchantOrderVO> queryMerchantOrderPage(int page, int size, Integer status, String beginTime, String endTime);

    MerchantOrderVO queryMerchantOrderDetail(Long orderId);

    void shipOrder(Long orderId);

    void refundOrder(Long orderId);

    OrderStatsDTO getMerchantOrderStats();

    List<SalesTrendDTO> getSalesTrend(Integer days);

    List<TopItemDTO> getTopItems(Integer limit);

    PageDTO<MerchantOrderVO> queryUserOrderPage(Long userId, int page, int size, Integer status);

    void applyRefund(Long orderId);

    void applyReturn(Long orderId);

    void cancelReturn(Long orderId);

    void approveReturn(Long orderId);

    void rejectReturn(Long orderId);

    void confirmReceive(Long orderId);

    void commentOrder(Long orderId);
}
