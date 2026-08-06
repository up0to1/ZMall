package com.hmall.trade.service;

import com.hmall.api.vo.MerchantOrderVO;
import com.hmall.common.domain.PageDTO;
import com.hmall.api.dto.OrderStatsDTO;
import com.hmall.api.dto.ProfitStatsDTO;
import com.hmall.api.dto.ProfitTrendDTO;
import com.hmall.api.dto.SalesTrendDTO;
import com.hmall.api.dto.TopItemDTO;
import com.hmall.trade.domain.dto.OrderFormDTO;
import com.hmall.trade.domain.dto.ShipOrderDTO;
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

    void shipOrder(Long orderId, ShipOrderDTO shipDTO);

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

    /**
     * 查询用户所有已完成订单中的 item_id 去重列表
     * 已完成订单状态：4（交易成功）、6（已评价）
     * 用于 US-AT-17 排除已购买的商品
     */
    List<Long> queryUserOrderItemIds(Long userId);

    /**
     * 商家后台-利润统计（按时间范围）
     * <p>利润 = 销售额 - 商品成本 - 运费 - 优惠折扣
     * @param days 统计近 N 天（null 表示全部）
     */
    ProfitStatsDTO getProfitStats(Integer days);

    /**
     * 商家后台-利润趋势（按天）
     * @param days 统计近 N 天
     */
    List<ProfitTrendDTO> getProfitTrend(Integer days);

    /**
     * 商品被物理删除时，标记所有引用该商品的 order_detail 快照
     * <p>将 name 改为 "【原商品名】商品已删除"，image 改为占位图，避免重复添加前缀。
     * <p>此接口仅供 item-service 通过 Feign 内部调用，禁止外部访问（网关已拦截 /orders/internal/**）。
     *
     * @param itemId   被删除的商品ID
     * @param itemName 被删除的商品名称（用于快照前缀）
     */
    void markItemDeletedInOrders(Long itemId, String itemName);

    /**
     * 用户删除单个订单（逻辑删除：user_deleted 置 1，进回收站）
     * <p>仅允许终态订单删除：status ∈ {4,5,6,8}
     * @param orderId 订单ID
     */
    void deleteOrder(Long orderId);

    /**
     * 用户批量删除订单（逻辑删除）
     * <p>仅允许终态订单删除：status ∈ {4,5,6,8}
     * @param orderIds 订单ID列表
     * @return 成功删除的数量
     */
    int batchDeleteOrders(List<Long> orderIds);

    /**
     * 用户从回收站恢复订单（user_deleted 置 0）
     * @param orderId 订单ID
     */
    void restoreOrder(Long orderId);

    /**
     * 用户回收站列表（仅查询 user_deleted=1 的订单）
     * @param userId 用户ID
     * @param page   页码
     * @param size   每页数量
     * @return 分页结果
     */
    PageDTO<MerchantOrderVO> queryTrashOrderPage(Long userId, int page, int size);
}
