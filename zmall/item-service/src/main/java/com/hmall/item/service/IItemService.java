package com.hmall.item.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.IService;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.OrderDetailDTO;
import com.hmall.item.domain.po.Item;
import java.util.Collection;
import java.util.List;
import java.util.Map;

public interface IItemService extends IService<Item> {

    void deductStock(List<OrderDetailDTO> items);

    void restoreStock(List<OrderDetailDTO> items);

    List<ItemDTO> queryItemByIds(Collection<Long> ids);

    Page<Item> queryMerchantPage(int page, int size, String keyword, Long merchantId);

    Page<Item> queryAdminPage(int page, int size, String name, Integer status, Integer itemType, Long merchantId);

    List<Item> getLowStockItems(int threshold, Long merchantId);

    void adjustStock(Long itemId, int targetStock);

    long countByStatus(Integer status, Long merchantId);

    /**
     * 新增商品（含EAV属性，事务性写入 item 表 + spu_attr_value 表）
     * <p>EAV 属性变更后自动触发 Qdrant 同步（穿搭类目）。
     */
    void saveItemWithEav(Item item, ItemDTO dto);

    /**
     * 更新商品（含EAV属性，事务性更新 item 表 + spu_attr_value 表）
     * <p>先删后插 EAV 属性值，EAV 变更后自动触发 Qdrant 同步（穿搭类目）。
     */
    void updateItemWithEav(Item item, ItemDTO dto);

    /**
     * 填充单个 DTO 的 EAV 属性（color/season/styleTags/sizes/material）
     */
    void fillEavAttrs(ItemDTO dto);

    /**
     * 批量填充 DTO 列表的 EAV 属性（用于列表查询，减少 N+1 查询）
     */
    void fillEavAttrsBatch(List<ItemDTO> dtos);

    /**
     * 批量查询商品实时库存（v6 工具拓展，供 Python ai-outfit 调用）
     * <p>优先查 Redis 缓存（item:stock:{id}，TTL 5 分钟），降级查数据库。
     *
     * @param itemIds 商品 ID 列表
     * @return {itemId: stock}，商品不存在时返回 0
     */
    Map<Long, Integer> batchQueryInventory(List<Long> itemIds);

    /**
     * 查询近 N 天销量 TopK 商品（v6 工具拓展·流行趋势，供 Python ai-outfit 调用）
     * <p>用于流行趋势服务，按销量降序返回热销商品。
     *
     * @param category 商品类目（中文，如 "上衣"），null 时查全品类
     * @param days     统计天数（如 30）
     * @param topK     返回前 K 条
     * @return ItemDTO 列表（含 id/name/image/category/price/sold 等字段，按销量降序）
     */
    List<ItemDTO> getTrendingItems(String category, int days, int topK);
}
