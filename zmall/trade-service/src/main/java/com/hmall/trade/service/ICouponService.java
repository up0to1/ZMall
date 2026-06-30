package com.hmall.trade.service;

import com.hmall.api.dto.CouponDTO;
import com.hmall.api.dto.CouponStatsDTO;
import com.hmall.api.vo.CouponVO;
import com.hmall.common.domain.PageDTO;

import java.util.List;

public interface ICouponService {

    void createCoupon(CouponDTO dto);

    void updateCoupon(Long id, CouponDTO dto);

    void deleteCoupon(Long id);

    PageDTO<CouponVO> queryCouponPage(int page, int size, Integer status, Integer couponType);

    void updateCouponStatus(Long id, Integer status);

    /** 更新优惠券类别（普通/秒杀） */
    void updateCouponType(Long id, Integer couponType);

    /** 设为秒杀优惠券（含秒杀信息） */
    void setSeckillCoupon(Long id, CouponDTO dto);

    /** 查询优惠券详情（含秒杀信息） */
    CouponVO getCouponDetail(Long id);

    CouponStatsDTO getCouponStats();

    /** 免费领取优惠券 */
    void receiveCoupon(Long couponId, Long userId);

    /** 校验付费优惠券是否可购买 */
    void purchaseCoupon(Long couponId, Long userId, Integer paymentType);

    /** 使用优惠券（下单时标记） */
    void useCoupon(Long couponId, Long userId, Long orderId);

    /** 优惠券购买订单支付成功后自动发货 */
    void deliverCouponOrder(Long orderId, Long userId, Long couponId);

    /** 优惠券退款（自动退，删除user_coupon） */
    void refundCouponOrder(Long orderId, Long userId, Long couponId);

    /** 查询优惠券适用商品ID列表 */
    List<Long> getCouponItemIds(Long couponId);

    /** 前台-查询可领取的优惠券列表 */
    PageDTO<CouponVO> queryAvailableCoupons(int page, int size, Integer couponType);

    /** 前台-查询商品可用优惠券列表 */
    List<CouponVO> queryItemCoupons(Long itemId);

    /** 前台-查询当前用户可用的优惠券（未使用） */
    List<CouponVO> queryUserAvailableCoupons(Long userId);

    /** 前台-查询当前用户每张优惠券的已领取数量 */
    java.util.Map<Long, Long> queryUserReceivedCount(Long userId);
}
