package com.hmall.item.controller;

import com.hmall.api.dto.AiOutfitHistoryDTO;
import com.hmall.api.dto.AiOutfitRecordCreateDTO;
import com.hmall.api.dto.AiOutfitRecordDTO;
import com.hmall.common.utils.UserContext;
import com.hmall.item.service.IAiOutfitRecordService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * AI 随心搭历史记录接口（用户端）
 *
 * 独立控制器，路径前缀 /items/outfit 不含 /admin/，
 * 避免被网关 MERCHANT_PATH_PATTERNS（/items/admin/**）拦截导致 403。
 *
 * 用户端写操作（满意/不满意标记、删除）也放在此 Controller，
 * Controller 层强制 userId = UserContext.getUser() 防止伪造。
 * Python 内部入库仍走 OutfitController POST /items/admin/outfit/records（不经网关）。
 */
@Api(tags = "AI 随心搭历史记录接口")
@RestController
@RequestMapping("/items/outfit")
@RequiredArgsConstructor
public class OutfitHistoryController {

    private final IAiOutfitRecordService aiOutfitRecordService;

    @ApiOperation("查询搭配历史（按 tab 分组，合并任务状态 + 搭配记录）")
    @GetMapping("/history")
    public List<AiOutfitHistoryDTO> queryMyHistory(
            @RequestParam(value = "tab", required = false, defaultValue = "all") String tab) {
        return aiOutfitRecordService.queryMyHistory(tab);
    }

    @ApiOperation("标记满意/不满意（用户端 upsert，复用 service 层 createRecord 逻辑）")
    @PostMapping("/records")
    public AiOutfitRecordDTO upsertMyRecord(@RequestBody AiOutfitRecordCreateDTO dto) {
        // 安全防护：强制 userId 为当前登录用户，防止伪造
        Long userId = UserContext.getUser();
        if (userId != null) {
            dto.setUserId(userId);
        }
        return aiOutfitRecordService.createRecord(dto);
    }

    @ApiOperation("删除搭配记录（仅本人可删）")
    @DeleteMapping("/records/{id}")
    public void deleteMyRecord(@PathVariable("id") Long id) {
        aiOutfitRecordService.deleteRecord(id);
    }

    @ApiOperation("取消满意联动删除衣橱条目（按 taskId + outfitIndex，结果页取消满意/改不满意时调用）")
    @DeleteMapping("/wardrobe/by-task")
    public void removeWardrobeByTask(
            @RequestParam("taskId") String taskId,
            @RequestParam("outfitIndex") Integer outfitIndex) {
        aiOutfitRecordService.removeWardrobeByTask(taskId, outfitIndex);
    }

    @ApiOperation("订单创建成功后标记搭配记录为已下单（trade-service 内部调用）")
    @PostMapping("/records/mark-ordered")
    public void markOutfitOrdered(
            @RequestParam(value = "recordId", required = false) Long recordId,
            @RequestParam(value = "taskId", required = false) String taskId,
            @RequestParam(value = "outfitIndex", required = false) Integer outfitIndex,
            @RequestParam("orderId") Long orderId,
            @RequestParam(value = "userId", required = false) Long userId) {
        // 用户端调用强制当前登录用户；服务间调用（Feign）无 UserContext，用传入的订单 userId
        Long cur = UserContext.getUser();
        aiOutfitRecordService.markOutfitOrdered(recordId, taskId, outfitIndex, orderId, cur != null ? cur : userId);
    }

    @ApiOperation("订单取消/超时未支付时回退搭配记录已下单状态（trade-service 内部调用）")
    @PostMapping("/records/revert-ordered")
    public void revertOutfitOrder(
            @RequestParam("orderId") Long orderId,
            @RequestParam(value = "userId", required = false) Long userId) {
        Long cur = UserContext.getUser();
        aiOutfitRecordService.revertOutfitOrder(orderId, cur != null ? cur : userId);
    }
}
