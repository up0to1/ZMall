package com.hmall.api.client;


import com.hmall.api.client.fallback.ItemClientFallbackFactory;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.OrderDetailDTO;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.domain.PageQuery;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.cloud.openfeign.SpringQueryMap;
import org.springframework.web.bind.annotation.*;

import java.util.Collection;
import java.util.List;

@FeignClient(value = "item-service", fallbackFactory = ItemClientFallbackFactory.class)
public interface ItemClient {

    // ========== 前台接口 ==========

    @GetMapping("/items")
    List<ItemDTO> queryItemByIds(@RequestParam("ids") Collection<Long> ids);

    @GetMapping("/items/{id}")
    ItemDTO queryItemById(@PathVariable("id") Long id);

    @GetMapping("/items/page")
    PageDTO<ItemDTO> queryItemPage(@SpringQueryMap PageQuery query);

    @PutMapping("/items/stock/deduct")
    void deductStock(@RequestBody Collection<OrderDetailDTO> items);

    @PutMapping("/items/stock/restore")
    void restoreStock(@RequestBody Collection<OrderDetailDTO> items);

    // ========== 后台管理接口 ==========

    @PostMapping("/items/admin")
    void saveItem(@RequestBody ItemDTO item);

    @PutMapping("/items/admin")
    void updateItem(@RequestBody ItemDTO item);

    @PutMapping("/items/admin/status/{id}/{status}")
    void updateItemStatus(@PathVariable("id") Long id, @PathVariable("status") Integer status);

    @PutMapping("/items/admin/itemType/{id}/{itemType}")
    void updateItemType(@PathVariable("id") Long id, @PathVariable("itemType") Integer itemType);

    @DeleteMapping("/items/admin/{id}")
    void deleteItem(@PathVariable("id") Long id);

    @PutMapping("/items/admin/stock/adjust/{id}")
    void adjustStock(@PathVariable("id") Long id, @RequestParam("targetStock") int targetStock);

    @GetMapping("/items/admin/stock/low")
    List<ItemDTO> getLowStockItems(@RequestParam("threshold") int threshold);

    @GetMapping("/items/admin/stock/page")
    PageDTO<ItemDTO> queryStockPage(@RequestParam("page") int page,
                                    @RequestParam("size") int size,
                                    @RequestParam("keyword") String keyword);

    @GetMapping("/items/admin/count")
    long countByStatus(@RequestParam("status") Integer status);

    @GetMapping("/items/admin/page")
    PageDTO<ItemDTO> queryAdminPage(@RequestParam("page") int page,
                                    @RequestParam("size") int size,
                                    @RequestParam(value = "name", required = false) String name,
                                    @RequestParam(value = "status", required = false) Integer status,
                                    @RequestParam(value = "itemType", required = false) Integer itemType);
}