package com.hmall.api.client.fallback;

import com.hmall.api.client.ItemClient;
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
        };
    }
}
