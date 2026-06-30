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
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

import static com.hmall.common.config.RedisConstants.CACHE_ITEM_KEY;

@Api(tags = "商品管理相关接口")
@RestController
@RequestMapping("/items")
@RequiredArgsConstructor
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
    @HotKeyCache(prefix = "cache:item:", keyParamIndex = 0, threshold = 10, hotCacheTime = 30, warmCacheTime = 5)
    @GetMapping("{id}")
    public ItemDTO queryItemById(@PathVariable("id") Long id) {
        return BeanUtils.copyBean(itemService.getById(id), ItemDTO.class);
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

    // ========== 后台管理接口 ==========

    @ApiOperation("新增商品")
    @PostMapping("/admin")
    public Long saveItem(@RequestBody ItemDTO item) {
        Item po = BeanUtils.copyBean(item, Item.class);
        po.setCreater(UserContext.getUser());
        itemService.save(po);
        return po.getId();
    }

    @ApiOperation("后台商品分页查询（支持筛选，按商家过滤）")
    @GetMapping("/admin/page")
    public PageDTO<ItemDTO> queryAdminPage(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size,
            @RequestParam(value = "name", required = false) String name,
            @RequestParam(value = "status", required = false) Integer status,
            @RequestParam(value = "itemType", required = false) Integer itemType) {
        Long merchantId = UserContext.getUser();
        Page<Item> result = itemService.queryAdminPage(page, size, name, status, itemType, merchantId);
        return PageDTO.of(result.getTotal(), result.getPages(), BeanUtils.copyList(result.getRecords(), ItemDTO.class));
    }

    @ApiOperation("更新商品状态")
    @PutMapping("/admin/status/{id}/{status}")
    public void updateItemStatus(@PathVariable("id") Long id, @PathVariable("status") Integer status){
        Item item = new Item();
        item.setId(id);
        item.setStatus(status);
        itemService.updateById(item);
        cacheClient.delete(CACHE_ITEM_KEY + id);
    }

    @ApiOperation("更新商品类别（普通/秒杀）")
    @PutMapping("/admin/itemType/{id}/{itemType}")
    public void updateItemType(@PathVariable("id") Long id, @PathVariable("itemType") Integer itemType){
        Item item = new Item();
        item.setId(id);
        item.setItemType(itemType);
        itemService.updateById(item);
        cacheClient.delete(CACHE_ITEM_KEY + id);
    }

    @ApiOperation("更新商品")
    @PutMapping("/admin")
    public void updateItem(@RequestBody ItemDTO item) {
        item.setStatus(null);
        itemService.updateById(BeanUtils.copyBean(item, Item.class));
        if (item.getId() != null) {
            cacheClient.delete(CACHE_ITEM_KEY + item.getId());
        }
    }

    @ApiOperation("根据id删除商品")
    @DeleteMapping("/admin/{id}")
    public void deleteItemById(@PathVariable("id") Long id) {
        itemService.removeById(id);
        cacheClient.delete(CACHE_ITEM_KEY + id);
    }

    @ApiOperation("库存调整")
    @PutMapping("/admin/stock/adjust/{id}")
    public void adjustStock(@PathVariable("id") Long id, @RequestParam("targetStock") int targetStock) {
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

    @ApiOperation("按状态统计商品数")
    @GetMapping("/admin/count")
    public long countByStatus(@RequestParam(value = "status", defaultValue = "1") Integer status) {
        return itemService.countByStatus(status);
    }

    @ApiOperation("文件上传（图片）")
    @PostMapping("/admin/upload")
    public String uploadFile(@RequestParam("file") MultipartFile file) {
        return fileStorageStrategy.upload(file, "items");
    }
}