package com.hmall.item.controller;

import com.hmall.api.dto.AiGeneratedModelImageDTO;
import com.hmall.api.dto.AiModelGenerateDTO;
import com.hmall.api.dto.AiModelImageFeedbackDTO;
import com.hmall.api.dto.AiModelPublishDTO;
import com.hmall.api.dto.AiModelRatingDTO;
import com.hmall.api.dto.AiModelRejectDTO;
import com.hmall.api.dto.AiTaskDTO;
import com.hmall.api.dto.SystemModelImageDTO;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.domain.PageQuery;
import com.hmall.common.utils.UserContext;
import com.hmall.item.service.IAiTaskService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * AI 模特图接口（商家端）
 *
 * <p>2026-07-19 v2 重构：取消三级模特图池，统一为系统模特图池。
 *
 * <p>商家提交 AI 模特任务的"二选一"约束（前端保证，后端 modelImageId 必填）：
 * <ul>
 *   <li>方式 A：商家上传新模特图（POST /system-images 上传 → 拿到 modelImageId → 调 generate）</li>
 *   <li>方式 B：商家从全平台共用的默认模特图池选一张（GET /system-images 列表 → 选 modelImageId → 调 generate）</li>
 *   <li>两者必选其一，不允许"无模特图"提交</li>
 * </ul>
 *
 * <p>商家上传的模特图作为系统默认模特图全平台共享；仅创建者可改删或切换展示/不展示。
 *
 * <p>流程：
 * <pre>
 *   ① 商家 GET /items/admin/ai-model/system-images 选模特图（也可 POST 上传新图入池）
 *   ② 商家 POST /items/admin/ai-model/generate { itemIds, modelImageId } → 异步生成
 *   ③ Python ai-models 消费 MQ → 链式 VTON 生成 N 张中间图 + 1 张最终图 → 发结果 MQ
 *   ④ Java 消费结果 MQ → 更新 ai_task 表 + 确认/回滚配额
 *   ⑤ 商家 GET /items/admin/ai-model/tasks 查任务列表 → 选定一张图
 *   ⑥ 商家 POST /items/admin/ai-model/publish { taskId, itemId, imageUrl } → 写回商品主图
 *
 *   系统模特图池：/items/admin/ai-model/system-images（全平台共用，仅创建者可改删）
 * </pre>
 *
 * <p>设计文档 §1.2 §1.8.10 §1.8.13（v2）
 */
@Api(tags = "AI 模特图相关接口")
@RestController
@RequestMapping("/items/admin/ai-model")
@RequiredArgsConstructor
public class AiModelController {

    private final IAiTaskService aiTaskService;

    @ApiOperation("提交 AI 模特图生成任务（异步，多商品链式 VTON）。modelImageId 必填：要么上传新图拿 ID，要么从默认池选 ID")
    @PostMapping("/generate")
    public AiTaskDTO generate(@RequestBody @Validated AiModelGenerateDTO dto) {
        return aiTaskService.createModelGenerateTask(dto);
    }

    @ApiOperation("发布模特图到商品主图（HIL：商家审阅满意后调用）")
    @PostMapping("/publish")
    public void publish(@RequestBody @Validated AiModelPublishDTO dto) {
        aiTaskService.publishModelImage(dto);
    }

    @ApiOperation("查询单个任务详情")
    @GetMapping("/task/{taskId}")
    public AiTaskDTO queryTask(@PathVariable("taskId") String taskId) {
        return aiTaskService.queryByTaskId(taskId);
    }

    @ApiOperation("查询当前商家的任务列表")
    @GetMapping("/tasks")
    public List<AiTaskDTO> queryMyTasks(@RequestParam(value = "status", required = false) String status) {
        return aiTaskService.queryMyTasks(status);
    }

    // ========== 系统模特图池（全平台共用，仅创建者可改删）==========

    @ApiOperation("查询系统模特图列表（所有商家都能查，分页）")
    @GetMapping("/system-images")
    public PageDTO<SystemModelImageDTO> listSystemImages(
            @RequestParam(value = "gender", required = false) String gender,
            @RequestParam(value = "skinTone", required = false) String skinTone,
            PageQuery pageQuery) {
        Long userId = UserContext.getUser();
        return aiTaskService.listSystemModelImages(gender, skinTone, userId, pageQuery);
    }

    @ApiOperation("上传并创建系统模特图（multipart 上传，自动入池，作为系统默认模特图全平台共享）")
    @PostMapping("/system-images")
    public SystemModelImageDTO createSystemImage(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "gender", required = false) String gender,
            @RequestParam(value = "skinTone", required = false) String skinTone,
            @RequestParam(value = "height", required = false) Integer height,
            @RequestParam(value = "weight", required = false) Integer weight,
            @RequestParam(value = "ageRange", required = false) String ageRange,
            @RequestParam(value = "bodyType", required = false) String bodyType,
            @RequestParam(value = "styleTags", required = false) List<String> styleTags,
            @RequestParam(value = "note", required = false) String note) {
        Long userId = UserContext.getUser();
        SystemModelImageDTO dto = new SystemModelImageDTO();
        dto.setGender(gender);
        dto.setSkinTone(skinTone);
        dto.setHeight(height);
        dto.setWeight(weight);
        dto.setAgeRange(ageRange);
        dto.setBodyType(bodyType);
        dto.setStyleTags(styleTags);
        dto.setNote(note);
        // 后端强制 isDefault=1（商家上传的均为系统默认模特图，无需前端手动设置）
        dto.setIsDefault(true);
        return aiTaskService.createSystemModelImage(file, dto, userId);
    }

    @ApiOperation("修改系统模特图元信息（仅创建者可操作）")
    @PutMapping("/system-images/{id}")
    public void updateSystemImage(@PathVariable("id") Long id,
                                  @RequestBody @Validated SystemModelImageDTO dto) {
        Long userId = UserContext.getUser();
        aiTaskService.updateSystemModelImage(id, dto, userId);
    }

    @ApiOperation("切换系统模特图展示/不展示（仅创建者可操作）。展示=全平台可用，不展示=其他商家和 AI 随心搭都不可用")
    @PutMapping("/system-images/{id}/visibility")
    public void updateSystemImageVisibility(@PathVariable("id") Long id,
                                             @RequestParam("isActive") Integer isActive) {
        Long userId = UserContext.getUser();
        aiTaskService.updateSystemModelImageVisibility(id, isActive, userId);
    }

    @ApiOperation("删除系统模特图（软删，仅创建者可操作）")
    @DeleteMapping("/system-images/{id}")
    public void deleteSystemImage(@PathVariable("id") Long id) {
        Long userId = UserContext.getUser();
        aiTaskService.deleteSystemModelImage(id, userId);
    }

    // ========== v3 评分与激励（2026-07-20 新增）==========

    @ApiOperation("商家对 AI 模特任务评分（≥3★ + saveToPool=true 时最终图自动入系统池）")
    @PostMapping("/tasks/{taskId}/rating")
    public AiModelImageFeedbackDTO rateTask(@PathVariable("taskId") String taskId,
                                            @RequestBody @Validated AiModelRatingDTO dto) {
        return aiTaskService.rateTask(taskId, dto.getStarRating(), dto.getRatingTags(),
                dto.getRatingNote(), dto.getSaveToPool());
    }

    @ApiOperation("商家提交拒绝原因（≥20 字可奖励 1 credit，每日上限 3 次）")
    @PostMapping("/tasks/{taskId}/reject-reason")
    public AiModelImageFeedbackDTO rejectTask(@PathVariable("taskId") String taskId,
                                              @RequestBody @Validated AiModelRejectDTO dto) {
        return aiTaskService.rejectTask(taskId, dto.getRejectReason());
    }

    @ApiOperation("AI 生成模特图入库（source=1=AI任务后保存 / source=3=AI自动生成，内部接口）")
    @PostMapping("/system-images/ai-generated")
    public SystemModelImageDTO createAiGeneratedImage(@RequestBody @Validated AiGeneratedModelImageDTO dto) {
        Long userId = UserContext.getUser();
        return aiTaskService.createAiGeneratedModelImage(
                dto.getImageUrl(), dto.getSource(), dto.getGender(), dto.getSkinTone(),
                dto.getStyleTags(), dto.getNote(), userId);
    }

    // ========== 内部接口（供 Python ai-outfit 调用，AI 随心搭兜底用）==========

    @ApiOperation("随机获取一张系统默认模特图（AI 随心搭兜底用，内部接口）")
    @GetMapping("/system-images/random-default")
    public SystemModelImageDTO getRandomDefaultModelImage() {
        return aiTaskService.getRandomDefaultModelImage();
    }
}
