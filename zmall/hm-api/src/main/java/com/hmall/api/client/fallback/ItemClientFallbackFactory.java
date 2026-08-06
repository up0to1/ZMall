package com.hmall.api.client.fallback;

import com.hmall.api.client.ItemClient;
import com.hmall.api.dto.AiModelGenerateDTO;
import com.hmall.api.dto.AiModelPublishDTO;
import com.hmall.api.dto.AiModelStatsDTO;
import com.hmall.api.dto.AiRatingDistDTO;
import com.hmall.api.dto.AiTaskDTO;
import com.hmall.api.dto.AiTaskTrendDTO;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.OrderDetailDTO;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.domain.PageQuery;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.utils.CollUtils;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;

import java.util.Collection;
import java.util.List;

@Slf4j
public class ItemClientFallbackFactory implements FallbackFactory<ItemClient> {

    @Override
    public ItemClient create(Throwable cause) {
        return new ItemClient() {
            // ========== 前台接口 ==========

            @Override
            public List<ItemDTO> queryItemByIds(Collection<Long> ids) {
                log.error("远程调用ItemClient#queryItemByIds方法出现异常，参数：{}", ids, cause);
                return CollUtils.emptyList();
            }

            @Override
            public ItemDTO queryItemById(Long id) {
                log.error("远程调用ItemClient#queryItemById方法出现异常，参数：{}", id, cause);
                return null;
            }

            @Override
            public PageDTO<ItemDTO> queryItemPage(PageQuery query) {
                log.error("远程调用ItemClient#queryItemPage方法出现异常", cause);
                return new PageDTO<>();
            }

            @Override
            public void deductStock(Collection<OrderDetailDTO> items) {
                log.error("远程调用ItemClient#deductStock方法出现异常", cause);
                throw new BizIllegalException("商品服务不可用，扣减库存失败", cause);
            }

            @Override
            public void restoreStock(Collection<OrderDetailDTO> items) {
                log.error("远程调用ItemClient#restoreStock方法出现异常", cause);
                throw new BizIllegalException("商品服务不可用，恢复库存失败", cause);
            }

            @Override
            public List<Long> queryItemIdsByCreater(Long creater) {
                log.error("远程调用ItemClient#queryItemIdsByCreater方法出现异常，参数：{}", creater, cause);
                return CollUtils.emptyList();
            }

            @Override
            public void updateItemTypeInternal(Long id, Integer itemType) {
                log.error("远程调用ItemClient#updateItemTypeInternal方法出现异常，参数：id={}, itemType={}", id, itemType, cause);
                throw new BizIllegalException("商品服务不可用，系统级更新商品类别失败", cause);
            }

            // ========== 后台管理接口 ==========

            @Override
            public void saveItem(ItemDTO item) {
                log.error("远程调用ItemClient#saveItem方法出现异常", cause);
                throw new BizIllegalException("商品服务不可用，新增商品失败", cause);
            }

            @Override
            public void updateItem(ItemDTO item) {
                log.error("远程调用ItemClient#updateItem方法出现异常", cause);
                throw new BizIllegalException("商品服务不可用，更新商品失败", cause);
            }

            @Override
            public void updateItemStatus(Long id, Integer status) {
                log.error("远程调用ItemClient#updateItemStatus方法出现异常，参数：id={}, status={}", id, status, cause);
                throw new BizIllegalException("商品服务不可用，更新商品状态失败", cause);
            }

            @Override
            public void updateItemType(Long id, Integer itemType) {
                log.error("远程调用ItemClient#updateItemType方法出现异常，参数：id={}, itemType={}", id, itemType, cause);
                throw new BizIllegalException("商品服务不可用，更新商品类别失败", cause);
            }

            @Override
            public void deleteItem(Long id) {
                log.error("远程调用ItemClient#deleteItem方法出现异常，参数：{}", id, cause);
                throw new BizIllegalException("商品服务不可用，删除商品失败", cause);
            }

            @Override
            public void adjustStock(Long id, int targetStock) {
                log.error("远程调用ItemClient#adjustStock方法出现异常，参数：id={}, targetStock={}", id, targetStock, cause);
                throw new BizIllegalException("商品服务不可用，调整库存失败", cause);
            }

            @Override
            public List<ItemDTO> getLowStockItems(int threshold) {
                log.error("远程调用ItemClient#getLowStockItems方法出现异常", cause);
                return CollUtils.emptyList();
            }

            @Override
            public PageDTO<ItemDTO> queryStockPage(int page, int size, String keyword) {
                log.error("远程调用ItemClient#queryStockPage方法出现异常", cause);
                return new PageDTO<>();
            }

            @Override
            public long countByStatus(Integer status) {
                log.error("远程调用ItemClient#countByStatus方法出现异常", cause);
                return 0;
            }

            @Override
            public PageDTO<ItemDTO> queryAdminPage(int page, int size, String name, Integer status, Integer itemType) {
                log.error("远程调用ItemClient#queryAdminPage方法出现异常", cause);
                return new PageDTO<>();
            }

            // ========== AI 模特图接口 ==========

            @Override
            public AiTaskDTO generateModelImage(AiModelGenerateDTO dto) {
                log.error("远程调用ItemClient#generateModelImage方法出现异常", cause);
                throw new BizIllegalException("商品服务不可用，AI 模特图生成失败", cause);
            }

            @Override
            public void publishModelImage(AiModelPublishDTO dto) {
                log.error("远程调用ItemClient#publishModelImage方法出现异常", cause);
                throw new BizIllegalException("商品服务不可用，AI 模特图发布失败", cause);
            }

            @Override
            public AiTaskDTO queryAiTask(String taskId) {
                log.error("远程调用ItemClient#queryAiTask方法出现异常，参数：{}", taskId, cause);
                return null;
            }

            @Override
            public List<AiTaskDTO> queryMyAiTasks(String status) {
                log.error("远程调用ItemClient#queryMyAiTasks方法出现异常", cause);
                return CollUtils.emptyList();
            }

            // ========== AI 数据看板接口 ==========

            @Override
            public AiModelStatsDTO getAiModelStatsOverview() {
                log.error("远程调用ItemClient#getAiModelStatsOverview方法出现异常", cause);
                return new AiModelStatsDTO();
            }

            @Override
            public List<AiTaskTrendDTO> getAiStatsTrend(int days) {
                log.error("远程调用ItemClient#getAiStatsTrend方法出现异常，参数：days={}", days, cause);
                return CollUtils.emptyList();
            }

            @Override
            public List<AiRatingDistDTO> getAiRatingDist() {
                log.error("远程调用ItemClient#getAiRatingDist方法出现异常", cause);
                return CollUtils.emptyList();
            }

            // ========== AI 随心搭订单联动接口（服务间调用） ==========

            @Override
            public void markOutfitOrdered(Long recordId, String taskId, Integer outfitIndex, Long orderId, Long userId) {
                log.error("远程调用ItemClient#markOutfitOrdered方法出现异常（仅告警，不影响下单），参数：recordId={}, taskId={}, outfitIndex={}, orderId={}",
                        recordId, taskId, outfitIndex, orderId, cause);
            }

            @Override
            public void revertOutfitOrder(Long orderId, Long userId) {
                log.error("远程调用ItemClient#revertOutfitOrder方法出现异常（仅告警，不影响取消），参数：orderId={}", orderId, cause);
            }
        };
    }
}
