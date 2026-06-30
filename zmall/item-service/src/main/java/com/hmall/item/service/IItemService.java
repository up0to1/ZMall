package com.hmall.item.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.IService;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.OrderDetailDTO;
import com.hmall.item.domain.po.Item;
import java.util.Collection;
import java.util.List;

public interface IItemService extends IService<Item> {

    void deductStock(List<OrderDetailDTO> items);

    void restoreStock(List<OrderDetailDTO> items);

    List<ItemDTO> queryItemByIds(Collection<Long> ids);

    Page<Item> queryMerchantPage(int page, int size, String keyword, Long merchantId);

    Page<Item> queryAdminPage(int page, int size, String name, Integer status, Integer itemType, Long merchantId);

    List<Item> getLowStockItems(int threshold, Long merchantId);

    void adjustStock(Long itemId, int targetStock);

    long countByStatus(Integer status);
}
