package com.hmall.item.controller;


import cn.hutool.core.thread.ThreadUtil;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmall.common.config.CacheClient;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.domain.PageQuery;
import com.hmall.common.hotkey.HotKeyCache;
import com.hmall.common.service.FileStorageStrategy;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.UserContext;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.OrderDetailDTO;
import com.hmall.item.domain.po.Item;
import com.hmall.item.service.IItemService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;
import java.util.Map;

import static com.hmall.common.config.RedisConstants.CACHE_ITEM_KEY;

@Api(tags = "商品管理相关接口")
@RestController
@RequestMapping("/items")
@RequiredArgsConstructor
@Slf4j
public class ItemController {

    private final IItemService itemService;

    private final FileStorageStrategy fileStorageStrategy;

    private final CacheClient cacheClient;

    // ========== 前台接口 ==========

    @ApiOperation("分页查询商品")
    @GetMapping("/page")
    public PageDTO<ItemDTO> queryItemByPage(PageQuery query) {
        Page<Item> result = itemService.page(new Page<>(query.getPageNo(), query.getPageSize()));
        return PageDTO.of(result.getTotal(), result.getPages(), BeanUtils.copyList(result.getRecords(), ItemDTO.class));
    }

    @ApiOperation("根据id批量查询商品")
    @GetMapping
    public List<ItemDTO> queryItemByIds(@RequestParam("ids") List<Long> ids){
        ThreadUtil.sleep(500);
        return itemService.queryItemByIds(ids);
    }

    @ApiOperation("根据id查询商品")
    @HotKeyCache(prefix = "cache:item:", keyParamIndex = 0, threshold = 50, hotCacheTime = 30, warmCacheTime = 5)
    @GetMapping("{id}")
    public ItemDTO queryItemById(@PathVariable("id") Long id) {
        ItemDTO dto = BeanUtils.copyBean(itemService.getById(id), ItemDTO.class);
        // 填充 EAV 属性（color/season/styleTags/sizes/material），来自 spu_attr_value 表
        itemService.fillEavAttrs(dto);
        // P0-3 修复：ITEM_VIEW 埋点已移至 ItemViewBehaviorAspect 切面（@Order(0) 包裹 @HotKeyCache），
        // 确保缓存命中时埋点也会执行。本方法只保留查询和 fillEavAttrs 逻辑。
        return dto;
    }

    @ApiOperation("扣减库存")
    @PutMapping("/stock/deduct")
    public void deductStock(@RequestBody List<OrderDetailDTO> items){
        itemService.deductStock(items);
    }

    @ApiOperation("恢复库存")
    @PutMapping("/stock/restore")
    public void restoreStock(@RequestBody List<OrderDetailDTO> items){
        itemService.restoreStock(items);
    }

    /**
     * 内部接口：按 creater 查询所有商品 ID（供 trade-service 查询商家订单用）
     * <p>路径 /items/internal/** 已在网关层禁止外部访问，仅供微服务间通过 FeignClient 调用。
     */
    @GetMapping("/internal/ids-by-creater")
    public List<Long> queryItemIdsByCreater(@RequestParam("creater") Long creater) {
        return itemService.list().stream()
                .filter(it -> creater.equals(it.getCreater()))
                .map(Item::getId)
                .collect(java.util.stream.Collectors.toList());
    }

    /**
     * 内部接口：更新商品类别（普通/秒杀），跳过商家所有权校验。
     * <p>仅用于系统级运维场景（如定时任务将到期秒杀商品自动转为普通商品），
     * 不应受商家"仅能操作自己商品"的权限限制。
     * <p>路径 /items/internal/** 已在网关层禁止外部访问，仅供微服务间通过 FeignClient 调用。
     */
    @PutMapping("/internal/{id}/itemType/{itemType}")
    public void updateItemTypeInternal(@PathVariable("id") Long id, @PathVariable("itemType") Integer itemType) {
        Item item = new Item();
        item.setId(id);
        item.setItemType(itemType);
        itemService.updateById(item);
        cacheClient.delete(CACHE_ITEM_KEY + id);
    }

    // ========== v6 工具拓展：内部接口（供 Python ai-outfit 调用）==========
    // 路径 /items/internal/** 已在网关层禁止外部访问，仅供微服务间通过 Nacos 发现 + HTTP 调用

    /**
     * 内部接口：批量查询商品实时库存（供 Python ai-outfit 库存工具调用）
     * <p>优先查 Redis 缓存（item:stock:{id}，TTL 5 分钟），降级查数据库。
     * <p>用于搭配推荐时过滤缺货商品，避免推荐已售罄商品。
     *
     * @param dto {"itemIds": [101, 102, 103]}
     * @return {101: 50, 102: 0, 103: 120}
     */
    @PostMapping("/internal/inventory/batch")
    public Map<Long, Integer> batchQueryInventory(@RequestBody InventoryQueryDTO dto) {
        return itemService.batchQueryInventory(dto.getItemIds());
    }

    /**
     * 内部接口：查询近 N 天销量 TopK 商品（供 Python ai-outfit 流行趋势工具调用）
     * <p>基于 item.sold 字段降序查询，仅返回上架商品。
     * <p>用于流行趋势服务，让 LLM 在搭配决策时参考当下热销商品风格。
     *
     * @param category 商品类目（中文，如 "上衣"），可选
     * @param days     统计天数（默认 30）
     * @param topK     返回前 K 条（默认 50）
     */
    @GetMapping("/internal/trending")
    public List<ItemDTO> getTrendingItems(
            @RequestParam(value = "category", required = false) String category,
            @RequestParam(value = "days", defaultValue = "30") int days,
            @RequestParam(value = "topK", defaultValue = "50") int topK) {
        return itemService.getTrendingItems(category, days, topK);
    }

    /**
     * v6 库存批量查询请求 DTO（内部接口用）
     */
    @lombok.Data
    public static class InventoryQueryDTO {
        private List<Long> itemIds;
    }

    // ========== 后台管理接口 ==========

    @ApiOperation("新增商品")
    @PostMapping("/admin")
    public Long saveItem(@RequestBody ItemDTO item) {
        Item po = BeanUtils.copyBean(item, Item.class);
        po.setCreater(UserContext.getUser());
        // P1-3 修复：SQL 默认 status=2（下架），若前端未传 status 则强制设为 1（上架）
        // 否则 ItemServiceImpl.save 中 isActive=(status==1) 判定为 false，
        // 同步到 Qdrant 时商品被标记为下架，AI 推荐永远不命中
        if (po.getStatus() == null) {
            po.setStatus(1);
        }
        // 事务性写入 item 表 + EAV 属性表（spu_attr_value）
        itemService.saveItemWithEav(po, item);
        return po.getId();
    }

    @ApiOperation("后台商品分页查询（支持筛选，按商家过滤）")
    @GetMapping("/admin/page")
    public PageDTO<ItemDTO> queryAdminPage(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size,
            @RequestParam(value = "name", required = false) String name,
            @RequestParam(value = "status", required = false) Integer status,
            @RequestParam(value = "itemType", required = false) Integer itemType,
            @RequestParam(value = "onlyMine", required = false) Boolean onlyMine) {
        Long merchantId = UserContext.getUser();
        // onlyMine=true 仅看自己商品；onlyMine=false 或 null 看全平台商品（CUD 操作仍有所有权校验）
        Long filterCreater = Boolean.TRUE.equals(onlyMine) ? merchantId : null;
        Page<Item> result = itemService.queryAdminPage(page, size, name, status, itemType, filterCreater);
        List<ItemDTO> dtos = BeanUtils.copyList(result.getRecords(), ItemDTO.class);
        // 批量填充 EAV 属性（color/season/styleTags/sizes/material），避免 N+1 查询
        itemService.fillEavAttrsBatch(dtos);
        return PageDTO.of(result.getTotal(), result.getPages(), dtos);
    }

    @ApiOperation("更新商品状态")
    @PutMapping("/admin/status/{id}/{status}")
    public void updateItemStatus(@PathVariable("id") Long id, @PathVariable("status") Integer status){
        checkItemOwnership(id);
        Item item = new Item();
        item.setId(id);
        item.setStatus(status);
        itemService.updateById(item);
        cacheClient.delete(CACHE_ITEM_KEY + id);
    }

    @ApiOperation("更新商品类别（普通/秒杀）")
    @PutMapping("/admin/itemType/{id}/{itemType}")
    public void updateItemType(@PathVariable("id") Long id, @PathVariable("itemType") Integer itemType){
        checkItemOwnership(id);
        Item item = new Item();
        item.setId(id);
        item.setItemType(itemType);
        itemService.updateById(item);
        cacheClient.delete(CACHE_ITEM_KEY + id);
    }

    @ApiOperation("更新商品")
    @PutMapping("/admin")
    public void updateItem(@RequestBody ItemDTO item) {
        if (item.getId() != null) {
            checkItemOwnership(item.getId());
        }
        item.setStatus(null);
        Item po = BeanUtils.copyBean(item, Item.class);
        // 事务性更新 item 表 + EAV 属性表（spu_attr_value 先删后插）
        itemService.updateItemWithEav(po, item);
        if (item.getId() != null) {
            cacheClient.delete(CACHE_ITEM_KEY + item.getId());
        }
    }

    @ApiOperation("根据id删除商品")
    @DeleteMapping("/admin/{id}")
    public void deleteItemById(@PathVariable("id") Long id) {
        checkItemOwnership(id);
        itemService.removeById(id);
        cacheClient.delete(CACHE_ITEM_KEY + id);
    }

    @ApiOperation("库存调整")
    @PutMapping("/admin/stock/adjust/{id}")
    public void adjustStock(@PathVariable("id") Long id, @RequestParam("targetStock") int targetStock) {
        checkItemOwnership(id);
        itemService.adjustStock(id, targetStock);
        cacheClient.delete(CACHE_ITEM_KEY + id);
    }

    @ApiOperation("低库存预警（按商家过滤）")
    @GetMapping("/admin/stock/low")
    public List<ItemDTO> getLowStockItems(@RequestParam(value = "threshold", defaultValue = "10") int threshold) {
        Long merchantId = UserContext.getUser();
        List<Item> items = itemService.getLowStockItems(threshold, merchantId);
        return BeanUtils.copyList(items, ItemDTO.class);
    }

    @ApiOperation("库存分页查询（含关键词搜索，按商家过滤）")
    @GetMapping("/admin/stock/page")
    public PageDTO<ItemDTO> queryStockPage(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size,
            @RequestParam(value = "keyword", required = false) String keyword) {
        Long merchantId = UserContext.getUser();
        Page<Item> result = itemService.queryMerchantPage(page, size, keyword, merchantId);
        return PageDTO.of(result.getTotal(), result.getPages(), BeanUtils.copyList(result.getRecords(), ItemDTO.class));
    }

    @ApiOperation("按状态统计商品数（按商家过滤）")
    @GetMapping("/admin/count")
    public long countByStatus(@RequestParam(value = "status", defaultValue = "1") Integer status) {
        Long merchantId = UserContext.getUser();
        return itemService.countByStatus(status, merchantId);
    }

    @ApiOperation("文件上传（图片）")
    @PostMapping("/admin/upload")
    public String uploadFile(@RequestParam("file") MultipartFile file) {
        return fileStorageStrategy.upload(file, "items");
    }

    /**
     * 商品所有权校验
     * <p>商家只能 CUD 自己 creater=userId 的商品，禁止越权操作他人商品。
     * <p>商品不存在时直接放行（交给后续 removeById/updateById 自行处理）。
     */
    private void checkItemOwnership(Long itemId) {
        if (itemId == null) {
            return;
        }
        Item item = itemService.getById(itemId);
        if (item == null) {
            return;
        }
        Long currentUserId = UserContext.getUser();
        if (currentUserId == null || !currentUserId.equals(item.getCreater())) {
            throw new com.hmall.common.exception.BizIllegalException("无权操作他人商品");
        }
    }
}