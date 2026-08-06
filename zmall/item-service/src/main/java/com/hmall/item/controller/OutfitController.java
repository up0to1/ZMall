package com.hmall.item.controller;

import com.hmall.api.dto.AiOutfitRecordCreateDTO;
import com.hmall.api.dto.AiOutfitRecordDTO;
import com.hmall.item.service.IAiOutfitRecordService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * AI 随心搭接口（用户端，v3 新增）
 *
 * <p>本 Controller 仅负责"满意套装入库 + 历史记录管理"。
 * 阶段一/阶段二的推荐生成、VTON 生成、反馈解析等核心逻辑由 Python ai-outfit 实现，
 * 前端直接调 Python ai-outfit 的 /api/v1/outfit/agent/* 接口。
 *
 * <p>接口分两类：
 * <ul>
 *   <li>用户端历史记录：GET /records, GET /records/{id}, DELETE /records/{id}（需 JWT 鉴权）</li>
 *   <li>Python 内部入库接口：POST /records（Python ai-outfit 在用户选满意-加购/下单时调用）</li>
 * </ul>
 *
 * <p>路径前缀 /items/admin/outfit：
 * <ul>
 *   <li>放在 /items/admin/ 下与 AI 模特图接口 /items/admin/ai-model/ 保持路径一致性</li>
 *   <li>"admin" 在此项目中含义是"已登录用户"，而非"管理员"，参考 AiModelController 路径约定</li>
 * </ul>
 *
 * <p>设计文档 §3.3.1 ⑨A/⑨B + §3.3.4 + §3.16.2
 */
@Api(tags = "AI 随心搭相关接口")
@RestController
@RequestMapping("/items/admin/outfit")
@RequiredArgsConstructor
public class OutfitController {

    private final IAiOutfitRecordService aiOutfitRecordService;

    // ========== Python 内部接口（用户满意加购/下单时入库）==========

    @ApiOperation("入库满意套装（Python ai-outfit 调用，用户选 [满意-加购整套] 或 [满意-下单整套] 时）")
    @PostMapping("/records")
    public AiOutfitRecordDTO createRecord(@RequestBody @Validated AiOutfitRecordCreateDTO dto) {
        return aiOutfitRecordService.createRecord(dto);
    }

    // ========== 用户端历史记录管理 ==========

    @ApiOperation("查询当前用户的搭配历史记录")
    @GetMapping("/records")
    public List<AiOutfitRecordDTO> queryMyRecords(
            @RequestParam(value = "accepted", required = false) Integer accepted) {
        return aiOutfitRecordService.queryMyRecords(accepted);
    }

    @ApiOperation("查询单条搭配记录详情")
    @GetMapping("/records/{id}")
    public AiOutfitRecordDTO queryRecord(@PathVariable("id") Long id) {
        return aiOutfitRecordService.queryById(id);
    }

    @ApiOperation("按 taskId + outfitIndex 查询记录（Python ai-outfit 内部调用，Redis 过期兜底）")
    @GetMapping("/records/by-task")
    public AiOutfitRecordDTO queryByTask(
            @RequestParam("taskId") String taskId,
            @RequestParam("outfitIndex") Integer outfitIndex) {
        return aiOutfitRecordService.queryByTaskAndIndex(taskId, outfitIndex);
    }

    @ApiOperation("删除搭配记录（仅本人可删）")
    @DeleteMapping("/records/{id}")
    public void deleteRecord(@PathVariable("id") Long id) {
        // 权限校验在 service 层完成（UserContext.getUser() + userId 匹配校验）
        aiOutfitRecordService.deleteRecord(id);
    }
}
