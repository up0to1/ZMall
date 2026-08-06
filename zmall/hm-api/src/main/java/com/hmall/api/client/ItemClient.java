package com.hmall.api.client;


import com.hmall.api.client.fallback.ItemClientFallbackFactory;
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

    /**
     * 服务间调用：按 creater 查询所有商品 ID
     * <p>用于 trade-service 查询商家的订单/库存/利润等数据时过滤商品集合。
     * 路径 /items/internal/** 已在网关层禁止外部访问。
     */
    @GetMapping("/items/internal/ids-by-creater")
    List<Long> queryItemIdsByCreater(@RequestParam("creater") Long creater);

    /**
     * 服务间调用：更新商品类别（普通/秒杀），跳过商家所有权校验。
     * <p>仅用于系统级运维场景，如定时任务将到期秒杀商品自动转为普通商品。
     * 路径 /items/internal/** 已在网关层禁止外部访问。
     */
    @PutMapping("/items/internal/{id}/itemType/{itemType}")
    void updateItemTypeInternal(@PathVariable("id") Long id, @PathVariable("itemType") Integer itemType);

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

    // ========== AI 模特图接口（商家端） ==========

    @PostMapping("/items/admin/ai-model/generate")
    AiTaskDTO generateModelImage(@RequestBody AiModelGenerateDTO dto);

    @PostMapping("/items/admin/ai-model/publish")
    void publishModelImage(@RequestBody AiModelPublishDTO dto);

    @GetMapping("/items/admin/ai-model/task/{taskId}")
    AiTaskDTO queryAiTask(@PathVariable("taskId") String taskId);

    @GetMapping("/items/admin/ai-model/tasks")
    List<AiTaskDTO> queryMyAiTasks(@RequestParam(value = "status", required = false) String status);

    // ========== AI 数据看板接口（商家端，阶段一：AI 模特图指标） ==========

    @GetMapping("/items/admin/ai-stats/overview")
    AiModelStatsDTO getAiModelStatsOverview();

    @GetMapping("/items/admin/ai-stats/trend")
    List<AiTaskTrendDTO> getAiStatsTrend(@RequestParam("days") int days);

    // ========== AI 随心搭订单联动接口（服务间调用） ==========

    /**
     * 服务间调用：订单创建成功后标记搭配记录为"已下单"（accepted=1 + acceptedAction=order + orderId）
     * <p>由 trade-service 下单成功后调用；recordId 为空时按 taskId + outfitIndex 定位记录。
     * <p>userId：下单用户ID（归属校验，内部调用时 trade-service 传入订单的 userId）。
     */
    @PostMapping("/items/outfit/records/mark-ordered")
    void markOutfitOrdered(@RequestParam(value = "recordId", required = false) Long recordId,
                           @RequestParam(value = "taskId", required = false) String taskId,
                           @RequestParam(value = "outfitIndex", required = false) Integer outfitIndex,
                           @RequestParam("orderId") Long orderId,
                           @RequestParam(value = "userId", required = false) Long userId);

    /**
     * 服务间调用：订单取消/超时未支付时回退搭配记录"已下单"状态
     * <p>恢复下单前的 accepted/action，清空 orderId；失败仅告警，不影响订单取消主流程。
     */
    @PostMapping("/items/outfit/records/revert-ordered")
    void revertOutfitOrder(@RequestParam("orderId") Long orderId,
                           @RequestParam(value = "userId", required = false) Long userId);

    @GetMapping("/items/admin/ai-stats/rating-dist")
    List<AiRatingDistDTO> getAiRatingDist();
}