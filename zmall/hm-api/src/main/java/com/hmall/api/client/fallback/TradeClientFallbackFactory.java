package com.hmall.api.client.fallback;

import com.hmall.api.client.TradeClient;
import com.hmall.api.vo.MerchantOrderVO;
import com.hmall.api.vo.CouponVO;
import com.hmall.api.vo.SeckillItemVO;
import com.hmall.api.dto.*;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.exception.BizIllegalException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;

import java.util.Collections;
import java.util.List;

@Slf4j
public class TradeClientFallbackFactory implements FallbackFactory<TradeClient> {

    @Override
    public TradeClient create(Throwable cause) {
        return new TradeClient() {
            @Override
            public void markOrderPaySuccess(Long orderId) {
                log.error("远程调用TradeClient#markOrderPaySuccess方法出现异常，参数：{}", orderId, cause);
                throw new BizIllegalException("交易服务不可用，标记支付成功失败", cause);
            }

            @Override
            public PageDTO<MerchantOrderVO> queryMerchantOrderPage(int page, int size, Integer status, String beginTime, String endTime) {
                log.error("远程调用TradeClient#queryMerchantOrderPage方法出现异常", cause);
                return new PageDTO<>();
            }

            @Override
            public MerchantOrderVO queryMerchantOrderDetail(Long orderId) {
                log.error("远程调用TradeClient#queryMerchantOrderDetail方法出现异常，参数：{}", orderId, cause);
                return null;
            }

            @Override
            public void shipOrder(Long orderId) {
                log.error("远程调用TradeClient#shipOrder方法出现异常，参数：{}", orderId, cause);
                throw new BizIllegalException("交易服务不可用，发货操作失败", cause);
            }

            @Override
            public void refundOrder(Long orderId) {
                log.error("远程调用TradeClient#refundOrder方法出现异常，参数：{}", orderId, cause);
                throw new BizIllegalException("交易服务不可用，退款操作失败", cause);
            }

            @Override
            public OrderStatsDTO getMerchantOrderStats() {
                log.error("远程调用TradeClient#getMerchantOrderStats方法出现异常", cause);
                return new OrderStatsDTO();
            }

            @Override
            public List<SalesTrendDTO> getSalesTrend(Integer days) {
                log.error("远程调用TradeClient#getSalesTrend方法出现异常", cause);
                return Collections.emptyList();
            }

            @Override
            public List<TopItemDTO> getTopItems(Integer limit) {
                log.error("远程调用TradeClient#getTopItems方法出现异常", cause);
                return Collections.emptyList();
            }

            @Override
            public void createCoupon(CouponDTO dto) {
                log.error("远程调用TradeClient#createCoupon方法出现异常", cause);
                throw new BizIllegalException("交易服务不可用，创建优惠券失败", cause);
            }

            @Override
            public void updateCoupon(Long id, CouponDTO dto) {
                log.error("远程调用TradeClient#updateCoupon方法出现异常，参数：id={}", id, cause);
                throw new BizIllegalException("交易服务不可用，更新优惠券失败", cause);
            }

            @Override
            public PageDTO<CouponVO> queryCouponPage(int page, int size) {
                log.error("远程调用TradeClient#queryCouponPage方法出现异常", cause);
                return new PageDTO<>();
            }

            @Override
            public void updateCouponStatus(Long id, Integer status) {
                log.error("远程调用TradeClient#updateCouponStatus方法出现异常，参数：id={}, status={}", id, status, cause);
                throw new BizIllegalException("交易服务不可用，更新优惠券状态失败", cause);
            }

            @Override
            public CouponStatsDTO getCouponStats() {
                log.error("远程调用TradeClient#getCouponStats方法出现异常", cause);
                return new CouponStatsDTO();
            }

            @Override
            public void createSeckill(SeckillItemDTO dto) {
                log.error("远程调用TradeClient#createSeckill方法出现异常", cause);
                throw new BizIllegalException("交易服务不可用，创建秒杀活动失败", cause);
            }

            @Override
            public List<SeckillItemVO> listSeckillItems() {
                log.error("远程调用TradeClient#listSeckillItems方法出现异常", cause);
                return Collections.emptyList();
            }

            @Override
            public void updateSeckillStock(Long itemId, Integer stock) {
                log.error("远程调用TradeClient#updateSeckillStock方法出现异常，参数：itemId={}, stock={}", itemId, stock, cause);
                throw new BizIllegalException("交易服务不可用，更新秒杀库存失败", cause);
            }

            @Override
            public void preheatStockToRedis(Long itemId) {
                log.error("远程调用TradeClient#preheatStockToRedis方法出现异常，参数：itemId={}", itemId, cause);
                throw new BizIllegalException("交易服务不可用，预热秒杀库存失败", cause);
            }

            @Override
            public int batchPreheatStock(List<Long> itemIds) {
                log.error("远程调用TradeClient#batchPreheatStock方法出现异常", cause);
                return 0;
            }

            @Override
            public void clearPreheat(Long itemId) {
                log.error("远程调用TradeClient#clearPreheat方法出现异常，参数：itemId={}", itemId, cause);
                throw new BizIllegalException("交易服务不可用，清除秒杀预热失败", cause);
            }
        };
    }
}
