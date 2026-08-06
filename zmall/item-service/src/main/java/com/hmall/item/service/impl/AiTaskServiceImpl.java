package com.hmall.item.service.impl;

import cn.hutool.core.bean.copier.CopyOptions;
import cn.hutool.core.lang.UUID;
import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.hmall.api.client.QuotaClient;
import com.hmall.api.constant.OutfitCategories;
import com.hmall.api.dto.AiModelGenerateDTO;
import com.hmall.api.dto.AiModelGenerateMessage;
import com.hmall.api.dto.AiModelImageFeedbackDTO;
import com.hmall.api.dto.AiModelPublishDTO;
import com.hmall.api.dto.AiModelResultMessage;
import com.hmall.api.dto.AiTaskDTO;
import com.hmall.api.dto.CreditsAwardDTO;
import com.hmall.api.dto.CreditsDeductDTO;
import com.hmall.api.dto.CreditsOperateDTO;
import com.hmall.api.dto.CreditsResultDTO;
import com.hmall.api.dto.SystemModelImageDTO;
import com.hmall.common.config.CacheClient;
import com.hmall.common.constants.MqConstants;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.domain.PageQuery;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.service.FileStorageStrategy;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.RabbitMqHelper;
import com.hmall.common.utils.UserContext;
import com.hmall.item.domain.po.AiModelImageFeedback;
import com.hmall.item.domain.po.AiTask;
import com.hmall.item.domain.po.Item;
import com.hmall.item.domain.po.SystemModelImage;
import com.hmall.item.mapper.AiModelImageFeedbackMapper;
import com.hmall.item.mapper.AiTaskMapper;
import com.hmall.item.mapper.SystemModelImageMapper;
import com.hmall.item.metrics.AiMetrics;
import com.hmall.item.service.IAiTaskService;
import com.hmall.item.service.IItemService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import static com.hmall.common.config.RedisConstants.CACHE_ITEM_KEY;

/**
 * AI 任务服务实现
 *
 * <p>2026-07-19 v2 重构：取消三级模特图池，统一为系统模特图池。
 *
 * <p>MQ Topic 设计：
 * <pre>
 * Exchange: ai.model.exchange (topic)
 *   ├─ ai.model.generate → Python ai-models 消费（任务下发）
 *   └─ ai.model.result   → Java item-service 消费（结果回流）
 * </pre>
 *
 * <p>设计文档 §1.0-§1.8（v2）
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AiTaskServiceImpl extends ServiceImpl<AiTaskMapper, AiTask> implements IAiTaskService {

    private final IItemService itemService;
    private final QuotaClient quotaClient;
    private final RabbitMqHelper rabbitMqHelper;
    private final CacheClient cacheClient;
    private final ObjectMapper objectMapper;
    private final StringRedisTemplate stringRedisTemplate;
    private final AiMetrics aiMetrics;
    private final SystemModelImageMapper systemModelImageMapper;
    private final AiModelImageFeedbackMapper aiModelImageFeedbackMapper;
    private final FileStorageStrategy fileStorageStrategy;

    /** 模特图上传子目录（本地模式：{basePath}/model-images/，OSS 模式：model-images/） */
    private static final String MODEL_IMAGE_DIR = "model-images";
    private static final String TASK_TYPE_MODEL = "MODEL";
    private static final String QUOTA_TYPE_MODEL = "MODEL";

    /** v3 评分激励常量（2026-07-20 新增） */
    private static final String FEEDBACK_TYPE_RATING = "RATING";
    private static final String FEEDBACK_TYPE_REJECT = "REJECT";
    private static final String AWARD_TYPE_RATING_PUBLISH = "RATING_PUBLISH";
    private static final String AWARD_TYPE_REJECT_REASON = "REJECT_REASON";
    private static final int DAILY_LIMIT_RATING_PUBLISH = 5;
    private static final int DAILY_LIMIT_REJECT_REASON = 3;
    private static final int REJECT_REASON_MIN_LENGTH = 20;
    private static final int RATING_THRESHOLD_SAVE_POOL = 3;
    private static final int RATING_THRESHOLD_AWARD_PUBLISH = 4;
    private static final int AWARD_CREDITS_PER_EVENT = 1;
    /** 同一商家同时进行中（PENDING/PROCESSING）的 AI 模特任务数上限 */
    private static final int MAX_CONCURRENT_TASKS_PER_USER = 3;

    /**
     * v5 多图模式 credits 阶梯（2026-07-26 新增）
     * <p>不同模式消耗不同 credits，反映资源成本差异：
     * <ul>
     *   <li>single：5 credits（基础链式 VTON，1 张图）</li>
     *   <li>multi_pose：动态公式 3 + poses * 3（1 次 VTON + N 次 O1 图生图，N=3-4 张图）</li>
     *   <li>multi_outfit：18 credits（N 次 VTON + N 次评估，N=2-4 张图，成本最高）</li>
     * </ul>
     */
    private static final int CREDITS_SINGLE = 5;
    private static final int CREDITS_MULTI_OUTFIT = 18;

    /** v5 多姿势模式默认姿势数 */
    private static final int DEFAULT_POSE_COUNT = 3;
    private static final int MAX_POSE_COUNT = 4;

    @Override
    public AiTaskDTO createModelGenerateTask(AiModelGenerateDTO dto) {
        Long userId = UserContext.getUser();
        if (userId == null) {
            throw new BizIllegalException("用户未登录");
        }

        List<Long> itemIds = dto.getItemIds();
        if (itemIds == null || itemIds.isEmpty()) {
            throw new BadRequestException("商品 ID 列表不能为空");
        }
        if (itemIds.size() > 4) {
            throw new BadRequestException("商品数量不能超过 4 件");
        }
        if (dto.getModelImageId() == null) {
            throw new BadRequestException("模特图 ID 不能为空");
        }

        // v5：解析生成模式（默认 single）
        String generationMode = StrUtil.isBlank(dto.getGenerationMode())
                ? "single" : dto.getGenerationMode();
        if (!"single".equals(generationMode)
                && !"multi_outfit".equals(generationMode)
                && !"multi_pose".equals(generationMode)) {
            throw new BadRequestException("非法的生成模式：" + generationMode
                    + "，支持 single / multi_outfit / multi_pose");
        }

        // v5：多姿势模式校验 poseCount
        Integer poseCount = null;
        if ("multi_pose".equals(generationMode)) {
            poseCount = dto.getPoseCount() != null ? dto.getPoseCount() : DEFAULT_POSE_COUNT;
            if (poseCount < 1 || poseCount > MAX_POSE_COUNT) {
                throw new BadRequestException("姿势数量必须在 1-" + MAX_POSE_COUNT + " 之间");
            }
        }

        // 1.批量查询商品并校验归属
        List<Item> items = itemService.listByIds(itemIds);
        if (items.size() != itemIds.size()) {
            throw new BadRequestException("部分商品不存在");
        }
        for (Item item : items) {
            if (!userId.equals(item.getCreater())) {
                throw new BizIllegalException("无权操作：商品 " + item.getId() + " 不属于当前商家");
            }
        }

        // 2.校验品类支持 + 品类冲突规则（按生成模式）
        // v5：multi_outfit 放宽同品类限制（允许 2 件下装+1 件上装）
        List<String> categories = items.stream()
                .map(Item::getCategory)
                .collect(Collectors.toList());
        String categoryError = OutfitCategories.validateAiModelCategoryCombo(categories, generationMode);
        if (categoryError != null) {
            throw new BadRequestException(categoryError);
        }

        // 2.1 并发限制：同一商家最多 MAX_CONCURRENT_TASKS_PER_USER 个进行中任务
        long activeCount = count(new LambdaQueryWrapper<AiTask>()
                .eq(AiTask::getUserId, userId)
                .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                .in(AiTask::getStatus, "PENDING", "PROCESSING"));
        if (activeCount >= MAX_CONCURRENT_TASKS_PER_USER) {
            throw new BizIllegalException("已有 " + activeCount + " 个任务在排队/生成中，上限 "
                    + MAX_CONCURRENT_TASKS_PER_USER + " 个，请等待完成后再提交");
        }

        // 3.解析模特图 URL（从系统模特图池）
        String modelImageUrl = resolveModelImageUrl(dto.getModelImageId());

        // 4.按 VTON 链式顺序排好商品（全身套装→上衣→下装→帽子）
        List<String> orderedCategories = OutfitCategories.sortByVtonChainOrder(categories);
        Map<String, Item> categoryToItem = new HashMap<>();
        for (Item item : items) {
            categoryToItem.put(item.getCategory(), item);
        }
        List<AiModelGenerateMessage.ItemInfo> orderedItems = new ArrayList<>();
        for (String cat : orderedCategories) {
            Item item = categoryToItem.get(cat);
            if (item != null) {
                // v5：扩展 ItemInfo，携带 name 供多换装 LLM 搭配推荐使用
                // color/styleTags 字段当前 Item 表无对应字段，留空（LLM 可基于品类+名称推理）
                AiModelGenerateMessage.ItemInfo info = new AiModelGenerateMessage.ItemInfo(
                        item.getId(), item.getImage(), cat
                );
                info.setName(item.getName());
                orderedItems.add(info);
            }
        }

        // 5.配额预扣（v5：按生成模式阶梯扣减 credits）
        int creditsToDeduct = calculateCredits(generationMode, poseCount);
        String taskId = UUID.randomUUID().toString(true);
        CreditsDeductDTO deductDTO = new CreditsDeductDTO();
        deductDTO.setType(QUOTA_TYPE_MODEL);
        deductDTO.setUserId(userId); // 商家维度：shopId = userId，credits 接口用 userId 字段
        deductDTO.setTaskId(taskId);
        deductDTO.setCredits(creditsToDeduct);
        deductDTO.setPhase("MODEL_GENERATE");
        CreditsResultDTO creditsResult = quotaClient.creditsDeduct(deductDTO);
        if (creditsResult == null || !Boolean.TRUE.equals(creditsResult.getSuccess())) {
            throw new BizIllegalException("AI credits 余额不足（需 " + creditsToDeduct + " credits）");
        }

        // 6.写 ai_task 表（status=PENDING，含 v5 多图模式字段）
        AiTask aiTask = new AiTask()
                .setTaskId(taskId)
                .setUserId(userId)
                .setShopId(userId) // 商家维度：shopId = userId
                .setItemId(itemIds.get(0)) // 保留首商品 ID 兼容旧逻辑
                .setTaskType(TASK_TYPE_MODEL)
                .setStatus("PENDING")
                .setInputParams(toJson(buildInputParams(dto)))
                .setItemIds(toJson(itemIds))
                .setEnableMultiAgent(0) // v4：默认关闭多 Agent 决策，后续按灰度策略开启
                .setGenerationMode(generationMode) // v5：记录生成模式
                .setCreatedAt(LocalDateTime.now());
        // v5：多换装模式持久化预设组合 + 推荐理由
        if ("multi_outfit".equals(generationMode) && dto.getOutfitCombinations() != null) {
            aiTask.setOutfitCombinations(toJson(dto.getOutfitCombinations()));
        }
        try {
            save(aiTask);
        } catch (Exception e) {
            // 补偿：落库失败时回滚已预扣的 credits，避免配额泄漏
            log.error("ai_task 落库失败，回滚 credits: taskId={}, error={}", taskId, e.getMessage(), e);
            CreditsOperateDTO rollbackDTO = new CreditsOperateDTO();
            rollbackDTO.setType(QUOTA_TYPE_MODEL);
            rollbackDTO.setUserId(userId); // 商家维度：shopId = userId
            rollbackDTO.setTaskId(taskId);
            try {
                quotaClient.creditsRollback(rollbackDTO);
            } catch (Exception ex) {
                log.error("credits 回滚失败（需人工对账）: taskId={}, error={}", taskId, ex.getMessage());
            }
            throw e;
        }
        log.info("AI 模特图任务已创建: taskId={}, itemIds={}, userId={}, mode={}, credits={}",
                taskId, itemIds, userId, generationMode, creditsToDeduct);

        // 7.发 MQ 任务消息（Java → Python，含 v5 多图模式字段）
        AiModelGenerateMessage message = new AiModelGenerateMessage();
        message.setTaskId(taskId);
        message.setUserId(userId);
        message.setShopId(userId);
        message.setItems(orderedItems);
        message.setItemIds(itemIds);
        message.setModelImageUrl(modelImageUrl);
        // v4：与 ai_task.enable_multi_agent 保持一致（当前默认 false）
        message.setEnableMultiAgent(Boolean.FALSE);
        // v5：传递生成模式 + 多换装组合 + 姿势数
        message.setGenerationMode(generationMode);
        if ("multi_outfit".equals(generationMode) && dto.getOutfitCombinations() != null) {
            message.setOutfitCombinations(dto.getOutfitCombinations());
        }
        if ("multi_pose".equals(generationMode) && poseCount != null) {
            message.setPoseCount(poseCount);
        }
        try {
            rabbitMqHelper.sendMessage(
                    MqConstants.AI_MODEL_EXCHANGE,
                    MqConstants.AI_MODEL_GENERATE_KEY,
                    message
            );
        } catch (Exception e) {
            log.error("MQ 发送失败，任务将靠超时补偿处理: taskId={}, error={}",
                    taskId, e.getMessage(), e);
        }

        // 8.返回 taskId 给前端（异步生成中）
        return toDTO(aiTask);
    }

    /**
     * v5：按生成模式计算 credits 扣减量
     * <ul>
     *   <li>single：5 credits（基础链式 VTON）</li>
     *   <li>multi_pose：12 credits（1 VTON + 3 O1 图生图；4 姿势则 15 credits）</li>
     *   <li>multi_outfit：18 credits（多套 VTON，固定成本）</li>
     * </ul>
     */
    private int calculateCredits(String generationMode, Integer poseCount) {
        switch (generationMode) {
            case "multi_pose":
                int poses = poseCount != null ? poseCount : DEFAULT_POSE_COUNT;
                // 每姿势 3 credits（含 1 次 O1 图生图）+ 基础 VTON 3 credits
                return 3 + poses * 3;
            case "multi_outfit":
                return CREDITS_MULTI_OUTFIT;
            case "single":
            default:
                return CREDITS_SINGLE;
        }
    }

    /**
     * 解析模特图 URL（从系统模特图池）
     *
     * <p>v2 简化：取消三级池，统一从 system_model_image 表查询。
     * 任何商家都能用 is_active=1 的模特图。
     */
    private String resolveModelImageUrl(Long modelImageId) {
        SystemModelImage img = systemModelImageMapper.selectById(modelImageId);
        if (img == null || !Integer.valueOf(1).equals(img.getIsActive())) {
            throw new BadRequestException("系统模特图不存在或已下架");
        }
        return img.getImageUrl();
    }

    @Override
    public void handleModelResult(AiModelResultMessage message) {
        // 修复 P1-5：移除方法级 @Transactional。
        // 修复 P0-2：与 AiTaskTimeoutScheduler 竞态保护——
        //   1) 先 SETNX 抢占"处理权"（合并并发互斥与幂等检查）
        //   2) 用条件更新 WHERE status IN (PENDING, PROCESSING) 写终态，避免覆盖 scheduler 已写入的 TIMEOUT
        //   3) update 返回 0 行说明已被 scheduler 标记 TIMEOUT 或已被另一消费者处理，跳过配额操作
        String taskId = message.getTaskId();
        if (StrUtil.isBlank(taskId)) {
            log.warn("收到空 taskId 的模特图结果消息，丢弃");
            return;
        }

        // 1.查 ai_task，已终态则跳过（ack 确认）
        AiTask aiTask = getOne(new LambdaQueryWrapper<AiTask>().eq(AiTask::getTaskId, taskId));
        if (aiTask == null) {
            log.warn("收到未知 taskId 的模特图结果消息: taskId={}", taskId);
            return;
        }
        if ("SUCCESS".equals(aiTask.getStatus()) || "FAILED".equals(aiTask.getStatus())
                || "TIMEOUT".equals(aiTask.getStatus())) {
            log.info("模特图任务已处理，跳过: taskId={}, status={}", taskId, aiTask.getStatus());
            return;
        }

        // 2.SETNX 抢占处理权（防并发消费同一条消息导致配额重复操作）
        String idempotentKey = MqConstants.AI_TASK_RESULT_IDEMPOTENT_PREFIX + taskId;
        Boolean acquired = stringRedisTemplate.opsForValue()
                .setIfAbsent(idempotentKey, "1", Duration.ofHours(1));
        if (Boolean.FALSE.equals(acquired)) {
            log.info("Redis 幂等标记已存在，跳过: taskId={}", taskId);
            return;
        }

        // 3.条件更新 ai_task 表（WHERE status IN (PENDING, PROCESSING)）
        // 与 AiTaskTimeoutScheduler 同款模式，避免覆盖 scheduler 已写入的 TIMEOUT
        LocalDateTime now = LocalDateTime.now();
        long costMs = aiTask.getCreatedAt() != null
                ? Duration.between(aiTask.getCreatedAt(), now).toMillis() : 0L;
        LambdaUpdateWrapper<AiTask> updateWrapper = new LambdaUpdateWrapper<AiTask>()
                .eq(AiTask::getId, aiTask.getId())
                .in(AiTask::getStatus, "PENDING", "PROCESSING")
                .set(AiTask::getStatus, message.getStatus())
                .set(AiTask::getFinishedAt, now)
                .set(AiTask::getCostMs, (int) costMs);
        if ("SUCCESS".equals(message.getStatus())) {
            updateWrapper.set(AiTask::getResultUrls, toJson(message.getResultUrls()));
            if (message.getItemCategories() != null) {
                updateWrapper.set(AiTask::getItemCategories, toJson(message.getItemCategories()));
            }
            if (message.getItemIds() != null) {
                updateWrapper.set(AiTask::getItemIds, toJson(message.getItemIds()));
            }
            // v4 多 Agent 决策字段：仅多 Agent 路径有值，链式 VTON 路径为 null（不覆盖默认值）
            if (message.getOverallScore() != null) {
                updateWrapper.set(AiTask::getOverallScore, message.getOverallScore());
            }
            if (message.getStyleFeatures() != null) {
                updateWrapper.set(AiTask::getStyleFeatures, message.getStyleFeatures());
            }
            if (message.getStyleFeaturesDivergence() != null) {
                updateWrapper.set(AiTask::getStyleFeaturesDivergence, message.getStyleFeaturesDivergence());
            }
            if (message.getPostProcessedImageUrl() != null) {
                updateWrapper.set(AiTask::getPostProcessedImageUrl, message.getPostProcessedImageUrl());
            }
            // v5 多图模式字段：agentEvaluations（5 角色评估详情）
            if (message.getAgentEvaluations() != null) {
                updateWrapper.set(AiTask::getAgentEvaluations, message.getAgentEvaluations());
            }
            // v5 多换装模式字段：outfitCombinations / combinationReasons / sceneResults
            if (message.getOutfitCombinations() != null) {
                updateWrapper.set(AiTask::getOutfitCombinations, toJson(message.getOutfitCombinations()));
            }
            if (message.getCombinationReasons() != null) {
                updateWrapper.set(AiTask::getCombinationReasons, toJson(message.getCombinationReasons()));
            }
            if (message.getSceneResults() != null) {
                updateWrapper.set(AiTask::getSceneResults, message.getSceneResults());
            }
            // v5 多姿势模式字段：poseResults
            if (message.getPoseResults() != null) {
                updateWrapper.set(AiTask::getPoseResults, message.getPoseResults());
            }
        } else {
            updateWrapper.set(AiTask::getErrorMsg, message.getErrorMsg());
        }
        boolean updated = update(updateWrapper);
        if (!updated) {
            // 状态已变更（通常是被 scheduler 标记 TIMEOUT），跳过配额操作避免双重操作
            log.info("任务状态已被并发变更，跳过配额操作: taskId={}, messageStatus={}",
                    taskId, message.getStatus());
            return;
        }

        // 4.credits 确认/回滚（P1-10 修复：MODEL 改走 /credits/confirm 和 /credits/rollback）
        // v2 取消模特图入池逻辑：上传即入池由 Java 上传接口完成
        Long shopId = aiTask.getShopId() != null ? aiTask.getShopId() : message.getShopId();
        CreditsOperateDTO operateDTO = new CreditsOperateDTO();
        operateDTO.setType(QUOTA_TYPE_MODEL);
        operateDTO.setUserId(shopId); // 商家维度：shopId = userId，credits 接口用 userId 字段
        operateDTO.setTaskId(taskId);
        try {
            if ("SUCCESS".equals(message.getStatus())) {
                quotaClient.creditsConfirm(operateDTO);
                log.info("credits 确认成功: taskId={}, shopId={}", taskId, shopId);
                aiMetrics.recordQuotaOperation(QUOTA_TYPE_MODEL, "confirm");
            } else {
                quotaClient.creditsRollback(operateDTO);
                log.info("credits 回滚成功: taskId={}, shopId={}", taskId, shopId);
                aiMetrics.recordQuotaOperation(QUOTA_TYPE_MODEL, "rollback");
            }
        } catch (Exception e) {
            log.error("credits 操作异常（可能已处理）: taskId={}, shopId={}, error={}",
                    taskId, shopId, e.getMessage());
            aiMetrics.recordQuotaOperation(QUOTA_TYPE_MODEL, "failed");
        }

        // 5.业务监控指标埋点
        aiMetrics.recordTaskComplete(aiTask.getTaskType(), message.getStatus());
        aiMetrics.recordTaskDuration(aiTask.getTaskType(), costMs);
    }

    @Override
    @Transactional
    public void publishModelImage(AiModelPublishDTO dto) {
        Long userId = UserContext.getUser();
        if (userId == null) {
            throw new BizIllegalException("用户未登录");
        }

        // 1.查询任务，校验归属
        AiTask aiTask = getOne(new LambdaQueryWrapper<AiTask>().eq(AiTask::getTaskId, dto.getTaskId()));
        if (aiTask == null) {
            throw new BadRequestException("任务不存在");
        }
        if (!userId.equals(aiTask.getUserId())) {
            throw new BizIllegalException("无权操作：任务不属于当前商家");
        }
        if (!"SUCCESS".equals(aiTask.getStatus())) {
            throw new BizIllegalException("任务未成功完成，无法发布");
        }

        // 2.校验图片 URL 在任务结果中
        List<String> urls = fromJsonList(aiTask.getResultUrls());
        if (urls == null || !urls.contains(dto.getImageUrl())) {
            throw new BadRequestException("图片 URL 不在任务结果中");
        }

        // 3.校验 itemId 在任务的商品列表中（防止跨店铺发布）
        List<Long> taskItemIds = fromJsonLongList(aiTask.getItemIds());
        if (taskItemIds == null || !taskItemIds.contains(dto.getItemId())) {
            throw new BadRequestException("商品 ID 不在任务的商品列表中");
        }

        // 4.追加 AI 模特图到商品详情图列表（detailImages）末尾 + 清缓存
        // 不动主图 image；detailImages 为 JSON 数组 ["url1","url2",...]
        Item item = itemService.getById(dto.getItemId());
        if (item == null) {
            throw new BadRequestException("商品不存在");
        }
        List<String> detailImages = fromJsonList(item.getDetailImages());
        if (detailImages == null) {
            detailImages = new ArrayList<>();
        }
        // 避免重复追加同一张图
        if (!detailImages.contains(dto.getImageUrl())) {
            detailImages.add(dto.getImageUrl());
        }
        Item update = new Item();
        update.setId(dto.getItemId());
        try {
            update.setDetailImages(objectMapper.writeValueAsString(detailImages));
        } catch (Exception e) {
            throw new BizIllegalException("序列化详情图列表失败: " + e.getMessage());
        }
        itemService.updateById(update);
        cacheClient.delete(CACHE_ITEM_KEY + dto.getItemId());

        // 5.v3 激励：≥4★ + 首次发布 → 奖 1 credit（每日上限 5 次）
        // 首次发布判定：ai_task.published_item_id 为 null（防重发放）
        // 失败不阻塞发布主流程，仅记日志
        boolean isFirstPublish = aiTask.getPublishedItemId() == null;
        if (isFirstPublish
                && aiTask.getStarRating() != null
                && aiTask.getStarRating() >= RATING_THRESHOLD_AWARD_PUBLISH) {
            try {
                if (tryAcquireAwardQuota(userId, AWARD_TYPE_RATING_PUBLISH, DAILY_LIMIT_RATING_PUBLISH)) {
                    CreditsAwardDTO awardDTO = new CreditsAwardDTO();
                    awardDTO.setUserId(userId);
                    awardDTO.setCredits(AWARD_CREDITS_PER_EVENT);
                    awardDTO.setAwardType(AWARD_TYPE_RATING_PUBLISH);
                    awardDTO.setBizRefId(dto.getTaskId());
                    quotaClient.creditsAward(awardDTO);
                    confirmAwardQuota(userId, AWARD_TYPE_RATING_PUBLISH);
                    log.info("发布奖励 credits 发放成功: taskId={}, userId={}, awardType={}",
                            dto.getTaskId(), userId, AWARD_TYPE_RATING_PUBLISH);
                } else {
                    log.info("今日 RATING_PUBLISH 奖励已达上限 {} 次，跳过: userId={}",
                            DAILY_LIMIT_RATING_PUBLISH, userId);
                }
            } catch (Exception e) {
                log.error("发布奖励 credits 发放失败（不阻塞主流程）: taskId={}, userId={}, error={}",
                        dto.getTaskId(), userId, e.getMessage());
            }
        }

        // 6.更新 ai_task.published_item_id（首次发布时写入，防重发布 + 统计发布转化率）
        if (isFirstPublish) {
            AiTask taskUpdate = new AiTask();
            taskUpdate.setId(aiTask.getId());
            taskUpdate.setPublishedItemId(dto.getItemId());
            updateById(taskUpdate);
        }

        log.info("AI 模特图已追加到商品详情图: taskId={}, itemId={}, imageUrl={}, starRating={}, firstPublish={}, detailImagesCount={}",
                dto.getTaskId(), dto.getItemId(), dto.getImageUrl(), aiTask.getStarRating(), isFirstPublish, detailImages.size());
    }

    @Override
    public AiTaskDTO queryByTaskId(String taskId) {
        Long userId = UserContext.getUser();
        AiTask aiTask = getOne(new LambdaQueryWrapper<AiTask>().eq(AiTask::getTaskId, taskId));
        if (aiTask == null) {
            return null;
        }
        // P5-2：权限校验，只能查自己店铺的任务（shopId = userId）
        if (userId != null && !userId.equals(aiTask.getUserId())) {
            log.warn("越权访问任务: taskId={}, currentUserId={}, taskUserId={}",
                    taskId, userId, aiTask.getUserId());
            throw new BizIllegalException("无权查看该任务");
        }
        AiTaskDTO dto = toDTO(aiTask);
        // PENDING 状态时填充排队位置
        if ("PENDING".equals(dto.getStatus()) && dto.getId() != null) {
            long aheadCount = count(new LambdaQueryWrapper<AiTask>()
                    .eq(AiTask::getStatus, "PENDING")
                    .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                    .lt(AiTask::getCreatedAt, aiTask.getCreatedAt()));
            dto.setQueuePosition((int) aheadCount);
        }
        return dto;
    }

    @Override
    public List<AiTaskDTO> queryMyTasks(String status) {
        Long userId = UserContext.getUser();
        if (userId == null) {
            return Collections.emptyList();
        }
        LambdaQueryWrapper<AiTask> wrapper = new LambdaQueryWrapper<AiTask>()
                .eq(AiTask::getUserId, userId)
                .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                .orderByDesc(AiTask::getCreatedAt);
        if (StrUtil.isNotBlank(status)) {
            wrapper.eq(AiTask::getStatus, status);
        }
        wrapper.last("LIMIT 100");
        List<AiTask> list = list(wrapper);
        // 不能用 BeanUtils.copyList，会触发 Hutool 把 ["76"] 转 List<Long> 失败；改用 toDTO 逐条处理
        List<AiTaskDTO> dtos = list.stream().map(this::toDTO).collect(Collectors.toList());

        // P5-1：为 PENDING 任务计算排队位置（前面有多少 PENDING 任务在排队）
        // 实现：一次性查询所有 PENDING 任务按 created_at 升序的 id 列表，
        // 用当前任务在队列中的位置作为 queuePosition
        List<AiTask> pendingTasks = list(new LambdaQueryWrapper<AiTask>()
                .eq(AiTask::getStatus, "PENDING")
                .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                .orderByAsc(AiTask::getCreatedAt));
        Map<Long, Integer> taskIdToQueuePos = new HashMap<>();
        for (int i = 0; i < pendingTasks.size(); i++) {
            // 队首任务 queuePosition=0，第二个=1，以此类推
            taskIdToQueuePos.put(pendingTasks.get(i).getId(), i);
        }
        for (AiTaskDTO dto : dtos) {
            if ("PENDING".equals(dto.getStatus()) && dto.getId() != null) {
                Integer pos = taskIdToQueuePos.get(dto.getId());
                dto.setQueuePosition(pos != null ? pos : 0);
            }
        }
        return dtos;
    }

    // ========== 系统模特图池 CRUD（全平台共用，仅创建者可改删）==========

    @Override
    public PageDTO<SystemModelImageDTO> listSystemModelImages(String gender, String skinTone, Long currentUserId, PageQuery pageQuery) {
        // 创建者可见自己下架（is_active=0）的图 + 所有展示中（is_active=1）的图
        // 其他商家只见 is_active=1 的图，下架的图不可见（包括 AI 随心搭兜底查询）
        LambdaQueryWrapper<SystemModelImage> wrapper = new LambdaQueryWrapper<SystemModelImage>()
                .and(w -> w.eq(SystemModelImage::getIsActive, 1)
                        .or().eq(SystemModelImage::getUploaderUserId, currentUserId))
                .orderByDesc(SystemModelImage::getIsActive)
                .orderByDesc(SystemModelImage::getIsDefault)
                .orderByAsc(SystemModelImage::getCreatedAt);
        if (StrUtil.isNotBlank(gender)) {
            wrapper.eq(SystemModelImage::getGender, gender);
        }
        if (StrUtil.isNotBlank(skinTone)) {
            wrapper.eq(SystemModelImage::getSkinTone, skinTone);
        }
        Page<SystemModelImage> page = new Page<>(pageQuery.getPageNo(), pageQuery.getPageSize());
        Page<SystemModelImage> result = systemModelImageMapper.selectPage(page, wrapper);
        List<SystemModelImageDTO> list = BeanUtils.copyList(result.getRecords(), SystemModelImageDTO.class,
                (po, dto) -> fillSystemModelImageDto(po, dto, currentUserId));
        return PageDTO.of(result.getTotal(), result.getPages(), list);
    }

    @Override
    @Transactional
    public SystemModelImageDTO createSystemModelImage(MultipartFile file, SystemModelImageDTO dto, Long currentUserId) {
        if (file == null || file.isEmpty()) {
            throw new BadRequestException("模特图文件不能为空");
        }

        // 1.直接上传原图（不加店铺水印，商家上传的均为系统默认模特图，全平台共享）
        String imageUrl;
        String originalFilename = file.getOriginalFilename();
        String contentType = file.getContentType();
        try {
            byte[] originalBytes = file.getBytes();
            imageUrl = fileStorageStrategy.upload(
                    originalBytes, originalFilename, contentType, MODEL_IMAGE_DIR);
            log.info("模特图已上传: userId={}, storageMode={}, imageUrl={}",
                    currentUserId, fileStorageStrategy.isOssMode() ? "oss" : "local", imageUrl);
        } catch (IOException e) {
            log.error("读取模特图文件 bytes 失败: userId={}, error={}", currentUserId, e.getMessage());
            throw new BadRequestException("模特图文件读取失败");
        }

        // 2.入库（商家上传的模特图均为系统默认图，强制 isDefault=1，无需手动设置）
        SystemModelImage entity = new SystemModelImage();
        entity.setImageUrl(imageUrl);
        entity.setUploaderUserId(currentUserId);
        entity.setGender(dto.getGender());
        entity.setSkinTone(dto.getSkinTone());
        entity.setHeight(dto.getHeight());
        entity.setWeight(dto.getWeight());
        entity.setAgeRange(dto.getAgeRange());
        entity.setBodyType(dto.getBodyType());
        entity.setStyleTags(dto.getStyleTags() != null ? toJson(dto.getStyleTags()) : null);
        entity.setNote(dto.getNote());
        entity.setIsDefault(1); // 强制系统默认图（移除前端手动设置）
        entity.setSource(0); // 0=商家上传
        entity.setIsActive(1);
        entity.setCreatedAt(LocalDateTime.now());
        entity.setUpdatedAt(LocalDateTime.now());
        systemModelImageMapper.insert(entity);
        log.info("系统模特图已创建: id={}, uploaderUserId={}", entity.getId(), currentUserId);

        // 3.返回 DTO
        SystemModelImageDTO result = BeanUtils.copyBean(entity, SystemModelImageDTO.class);
        fillSystemModelImageDto(entity, result, currentUserId);
        return result;
    }

    @Override
    public void updateSystemModelImage(Long id, SystemModelImageDTO dto, Long currentUserId) {
        SystemModelImage existing = systemModelImageMapper.selectById(id);
        if (existing == null || !Integer.valueOf(1).equals(existing.getIsActive())) {
            throw new BadRequestException("模特图不存在或已下架");
        }
        // 权限校验：仅创建者可修改
        if (!currentUserId.equals(existing.getUploaderUserId())) {
            throw new BizIllegalException("无权操作：仅创建者可修改模特图");
        }
        SystemModelImage update = new SystemModelImage();
        update.setId(id);
        if (dto.getGender() != null) update.setGender(dto.getGender());
        if (dto.getSkinTone() != null) update.setSkinTone(dto.getSkinTone());
        if (dto.getHeight() != null) update.setHeight(dto.getHeight());
        if (dto.getWeight() != null) update.setWeight(dto.getWeight());
        if (dto.getAgeRange() != null) update.setAgeRange(dto.getAgeRange());
        if (dto.getBodyType() != null) update.setBodyType(dto.getBodyType());
        if (dto.getStyleTags() != null) update.setStyleTags(toJson(dto.getStyleTags()));
        if (dto.getNote() != null) update.setNote(dto.getNote());
        if (dto.getIsDefault() != null) update.setIsDefault(Boolean.TRUE.equals(dto.getIsDefault()) ? 1 : 0);
        update.setUpdatedAt(LocalDateTime.now());
        systemModelImageMapper.updateById(update);
    }

    @Override
    public void deleteSystemModelImage(Long id, Long currentUserId) {
        SystemModelImage existing = systemModelImageMapper.selectById(id);
        if (existing == null) {
            throw new BadRequestException("模特图不存在");
        }
        // 权限校验：仅创建者可删除
        if (!currentUserId.equals(existing.getUploaderUserId())) {
            throw new BizIllegalException("无权操作：仅创建者可删除模特图");
        }
        // 软删（保留历史任务可追溯）
        SystemModelImage update = new SystemModelImage();
        update.setId(id);
        update.setIsActive(0);
        update.setUpdatedAt(LocalDateTime.now());
        systemModelImageMapper.updateById(update);
    }

    @Override
    public void updateSystemModelImageVisibility(Long id, Integer isActive, Long currentUserId) {
        SystemModelImage existing = systemModelImageMapper.selectById(id);
        if (existing == null) {
            throw new BadRequestException("模特图不存在");
        }
        // 权限校验：仅创建者可切换展示状态
        if (!currentUserId.equals(existing.getUploaderUserId())) {
            throw new BizIllegalException("无权操作：仅创建者可修改模特图展示状态");
        }
        if (isActive == null || (isActive != 0 && isActive != 1)) {
            throw new BadRequestException("非法的展示状态参数");
        }
        // 避免重复更新
        if (isActive.equals(existing.getIsActive())) {
            return;
        }
        SystemModelImage update = new SystemModelImage();
        update.setId(id);
        update.setIsActive(isActive);
        update.setUpdatedAt(LocalDateTime.now());
        systemModelImageMapper.updateById(update);
        log.info("模特图展示状态已切换: id={}, isActive={}, operator={}", id, isActive, currentUserId);
    }

    @Override
    public SystemModelImageDTO getRandomDefaultModelImage() {
        // 优先 is_default=1 的
        LambdaQueryWrapper<SystemModelImage> wrapper = new LambdaQueryWrapper<SystemModelImage>()
                .eq(SystemModelImage::getIsActive, 1)
                .eq(SystemModelImage::getIsDefault, 1)
                .last("LIMIT 1");
        SystemModelImage img = systemModelImageMapper.selectOne(wrapper);
        if (img == null) {
            // 兜底：取任意一张 active 的
            LambdaQueryWrapper<SystemModelImage> fallback = new LambdaQueryWrapper<SystemModelImage>()
                    .eq(SystemModelImage::getIsActive, 1)
                    .orderByDesc(SystemModelImage::getCreatedAt)
                    .last("LIMIT 1");
            img = systemModelImageMapper.selectOne(fallback);
        }
        if (img == null) {
            return null;
        }
        SystemModelImageDTO dto = BeanUtils.copyBean(img, SystemModelImageDTO.class);
        fillSystemModelImageDto(img, dto, null);
        return dto;
    }

    // ========== v3 评分与激励（2026-07-20 新增）==========

    @Override
    @Transactional
    public AiModelImageFeedbackDTO rateTask(String taskId, Integer starRating,
                                             List<String> ratingTags, String ratingNote,
                                             Boolean saveToPool) {
        Long userId = UserContext.getUser();
        if (userId == null) {
            throw new BizIllegalException("用户未登录");
        }

        // 1.查任务，校验归属 + SUCCESS 状态
        AiTask aiTask = getOne(new LambdaQueryWrapper<AiTask>().eq(AiTask::getTaskId, taskId));
        if (aiTask == null) {
            throw new BadRequestException("任务不存在");
        }
        if (!userId.equals(aiTask.getUserId())) {
            throw new BizIllegalException("无权操作：任务不属于当前商家");
        }
        if (!"SUCCESS".equals(aiTask.getStatus())) {
            throw new BizIllegalException("任务未成功完成，无法评分");
        }

        // 2.校验是否已评分（uk_task_id_type 唯一索引兜底，防止并发重复评分）
        AiModelImageFeedback existing = aiModelImageFeedbackMapper.selectOne(
                new LambdaQueryWrapper<AiModelImageFeedback>()
                        .eq(AiModelImageFeedback::getTaskId, taskId)
                        .eq(AiModelImageFeedback::getFeedbackType, FEEDBACK_TYPE_RATING));
        if (existing != null) {
            throw new BadRequestException("该任务已评分，无法重复评分");
        }

        // 3.取最终图 URL（链式 VTON 的最后一张为最终图）
        List<String> urls = fromJsonList(aiTask.getResultUrls());
        String finalUrl = (urls != null && !urls.isEmpty()) ? urls.get(urls.size() - 1) : null;

        // 4.写 feedback 记录（评分时不奖励 credits，发布时才奖励）
        AiModelImageFeedback feedback = new AiModelImageFeedback()
                .setTaskId(taskId)
                .setUserId(userId)
                .setShopId(aiTask.getShopId())
                .setFeedbackType(FEEDBACK_TYPE_RATING)
                .setStarRating(starRating)
                .setRatingTags(ratingTags != null ? toJson(ratingTags) : null)
                .setRatingNote(ratingNote)
                .setResultUrl(finalUrl)
                .setItemIds(aiTask.getItemIds())
                .setAwardedCredits(0)
                .setSavedToPool(0)
                .setCreatedAt(LocalDateTime.now());
        aiModelImageFeedbackMapper.insert(feedback);

        // 5.≥3★ + 商家同意 → 最终图自动入 system_model_image 池（source=1）
        // 失败不阻塞主流程，仅记日志（商家可后续手动上传）
        if (Boolean.TRUE.equals(saveToPool)
                && starRating != null
                && starRating >= RATING_THRESHOLD_SAVE_POOL
                && finalUrl != null) {
            try {
                createAiGeneratedModelImage(finalUrl, 1, null, null,
                        ratingTags, ratingNote, userId);
                // 更新 feedback 入池状态
                AiModelImageFeedback feedbackUpdate = new AiModelImageFeedback();
                feedbackUpdate.setId(feedback.getId());
                feedbackUpdate.setSavedToPool(1);
                aiModelImageFeedbackMapper.updateById(feedbackUpdate);
                feedback.setSavedToPool(1);
                log.info("最终图已入系统模特图池: taskId={}, imageUrl={}", taskId, finalUrl);
            } catch (Exception e) {
                log.error("最终图入池失败（不阻塞主流程）: taskId={}, imageUrl={}, error={}",
                        taskId, finalUrl, e.getMessage());
            }
        }

        // 6.更新 ai_task 评分字段
        AiTask taskUpdate = new AiTask();
        taskUpdate.setId(aiTask.getId());
        taskUpdate.setStarRating(starRating);
        taskUpdate.setRatingTags(ratingTags != null ? toJson(ratingTags) : null);
        taskUpdate.setRatingNote(ratingNote);
        if (feedback.getSavedToPool() != null && feedback.getSavedToPool() == 1) {
            taskUpdate.setSavedToPool(1);
        }
        updateById(taskUpdate);

        log.info("AI 模特任务评分成功: taskId={}, starRating={}, savedToPool={}",
                taskId, starRating, feedback.getSavedToPool());

        return toFeedbackDTO(feedback);
    }

    @Override
    @Transactional
    public AiModelImageFeedbackDTO rejectTask(String taskId, String rejectReason) {
        Long userId = UserContext.getUser();
        if (userId == null) {
            throw new BizIllegalException("用户未登录");
        }

        // 1.查任务，校验归属
        AiTask aiTask = getOne(new LambdaQueryWrapper<AiTask>().eq(AiTask::getTaskId, taskId));
        if (aiTask == null) {
            throw new BadRequestException("任务不存在");
        }
        if (!userId.equals(aiTask.getUserId())) {
            throw new BizIllegalException("无权操作：任务不属于当前商家");
        }
        if (!"SUCCESS".equals(aiTask.getStatus()) && !"FAILED".equals(aiTask.getStatus())
                && !"TIMEOUT".equals(aiTask.getStatus())) {
            throw new BizIllegalException("任务未完成，无法提交拒绝原因");
        }

        // 2.校验是否已拒绝（uk_task_id_type 唯一索引兜底）
        AiModelImageFeedback existing = aiModelImageFeedbackMapper.selectOne(
                new LambdaQueryWrapper<AiModelImageFeedback>()
                        .eq(AiModelImageFeedback::getTaskId, taskId)
                        .eq(AiModelImageFeedback::getFeedbackType, FEEDBACK_TYPE_REJECT));
        if (existing != null) {
            throw new BadRequestException("该任务已提交拒绝原因，无法重复提交");
        }

        // 3.计算奖励：rejectReason ≥20 字 + 当日 REJECT_REASON 奖励次数 <3
        // creditsAward 调用失败不阻塞主流程，feedback 记录 awarded_credits=0
        int awardedCredits = 0;
        if (rejectReason != null && rejectReason.length() >= REJECT_REASON_MIN_LENGTH) {
            if (tryAcquireAwardQuota(userId, AWARD_TYPE_REJECT_REASON, DAILY_LIMIT_REJECT_REASON)) {
                try {
                    CreditsAwardDTO awardDTO = new CreditsAwardDTO();
                    awardDTO.setUserId(userId);
                    awardDTO.setCredits(AWARD_CREDITS_PER_EVENT);
                    awardDTO.setAwardType(AWARD_TYPE_REJECT_REASON);
                    awardDTO.setBizRefId(taskId);
                    quotaClient.creditsAward(awardDTO);
                    confirmAwardQuota(userId, AWARD_TYPE_REJECT_REASON);
                    awardedCredits = AWARD_CREDITS_PER_EVENT;
                    log.info("拒绝原因奖励 credits 发放成功: taskId={}, userId={}", taskId, userId);
                } catch (Exception e) {
                    log.error("拒绝原因 credits 奖励发放失败（不阻塞主流程）: taskId={}, userId={}, error={}",
                            taskId, userId, e.getMessage());
                }
            } else {
                log.info("今日 REJECT_REASON 奖励已达上限 {} 次，跳过: userId={}",
                        DAILY_LIMIT_REJECT_REASON, userId);
            }
        } else if (rejectReason != null) {
            log.info("拒绝原因长度不足 {} 字，不发放奖励: taskId={}, length={}",
                    REJECT_REASON_MIN_LENGTH, taskId, rejectReason.length());
        }

        // 4.写 feedback 记录
        AiModelImageFeedback feedback = new AiModelImageFeedback()
                .setTaskId(taskId)
                .setUserId(userId)
                .setShopId(aiTask.getShopId())
                .setFeedbackType(FEEDBACK_TYPE_REJECT)
                .setRejectReason(rejectReason)
                .setItemIds(aiTask.getItemIds())
                .setAwardedCredits(awardedCredits)
                .setSavedToPool(0)
                .setCreatedAt(LocalDateTime.now());
        aiModelImageFeedbackMapper.insert(feedback);

        // 5.更新 ai_task.reject_reason
        AiTask taskUpdate = new AiTask();
        taskUpdate.setId(aiTask.getId());
        taskUpdate.setRejectReason(rejectReason);
        updateById(taskUpdate);

        log.info("AI 模特任务拒绝原因已记录: taskId={}, reasonLength={}, awardedCredits={}",
                taskId, rejectReason != null ? rejectReason.length() : 0, awardedCredits);

        return toFeedbackDTO(feedback);
    }

    @Override
    public SystemModelImageDTO createAiGeneratedModelImage(String imageUrl, Integer source,
                                                            String gender, String skinTone,
                                                            List<String> styleTags, String note,
                                                            Long uploaderUserId) {
        if (StrUtil.isBlank(imageUrl)) {
            throw new BadRequestException("imageUrl 不能为空");
        }
        if (source == null || (source != 1 && source != 3)) {
            throw new BadRequestException("source 必须为 1（AI任务后保存）或 3（AI自动生成）");
        }

        // 直接入库（无需文件上传，imageUrl 已经是 OSS/本地存储路径）
        SystemModelImage entity = new SystemModelImage();
        entity.setImageUrl(imageUrl);
        entity.setUploaderUserId(uploaderUserId);
        entity.setGender(gender);
        entity.setSkinTone(skinTone);
        entity.setStyleTags(styleTags != null ? toJson(styleTags) : null);
        entity.setNote(note);
        entity.setIsDefault(0); // AI 生成的不作为默认图
        entity.setSource(source);
        entity.setIsActive(1);
        entity.setCreatedAt(LocalDateTime.now());
        entity.setUpdatedAt(LocalDateTime.now());
        systemModelImageMapper.insert(entity);
        log.info("AI 生成模特图已入池: id={}, source={}, imageUrl={}",
                entity.getId(), source, imageUrl);

        SystemModelImageDTO result = BeanUtils.copyBean(entity, SystemModelImageDTO.class);
        fillSystemModelImageDto(entity, result, uploaderUserId);
        return result;
    }

    // ========== 辅助方法 ==========

    private AiTaskDTO toDTO(AiTask aiTask) {
        // 忽略 PO 中存为 JSON 字符串、DTO 中为 List 的字段，避免 Hutool 自动转换失败（如 ["76"] → List<Long>）
        // 这些字段由下面的 fillDto 用 fromJsonList/fromJsonLongList 正确反序列化填充
        CopyOptions options = CopyOptions.create().setIgnoreProperties(
                "itemIds", "outfitItems", "resultUrls", "itemCategories", "ratingTags");
        AiTaskDTO dto = BeanUtils.toBean(aiTask, AiTaskDTO.class, options);
        return fillDto(aiTask, dto);
    }

    private AiTaskDTO fillDto(AiTask aiTask, AiTaskDTO dto) {
        dto.setResultUrls(fromJsonList(aiTask.getResultUrls()));
        dto.setOutfitItems(fromJsonLongList(aiTask.getOutfitItems()));
        dto.setItemIds(fromJsonLongList(aiTask.getItemIds()));
        dto.setItemCategories(fromJsonList(aiTask.getItemCategories()));
        dto.setRatingTags(fromJsonList(aiTask.getRatingTags()));
        // 排队位置：仅 PENDING 状态计算（前面还有几个 PENDING/PROCESSING 任务）
        if ("PENDING".equals(aiTask.getStatus())) {
            long ahead = count(new LambdaQueryWrapper<AiTask>()
                    .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                    .in(AiTask::getStatus, "PENDING", "PROCESSING")
                    .lt(AiTask::getCreatedAt, aiTask.getCreatedAt()));
            dto.setQueuePosition((int) ahead);
        }
        return dto;
    }

    private void fillSystemModelImageDto(SystemModelImage po, SystemModelImageDTO dto, Long currentUserId) {
        if (po.getStyleTags() != null) {
            dto.setStyleTags(fromJsonList(po.getStyleTags()));
        }
        if (po.getIsDefault() != null) {
            dto.setIsDefault(po.getIsDefault() == 1);
        }
        if (po.getSource() != null) {
            dto.setSource(po.getSource());
        }
        if (po.getIsActive() != null) {
            dto.setIsActive(po.getIsActive());
        }
        // 标记是否为当前用户上传（前端据此显示编辑/删除按钮）
        dto.setMine(currentUserId != null && currentUserId.equals(po.getUploaderUserId()));
    }

    private Map<String, Object> buildInputParams(AiModelGenerateDTO dto) {
        Map<String, Object> params = new HashMap<>();
        params.put("itemIds", dto.getItemIds());
        params.put("modelImageId", dto.getModelImageId());
        return params;
    }

    private String toJson(Object obj) {
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            log.warn("JSON 序列化失败: {}", e.getMessage());
            return null;
        }
    }

    private List<String> fromJsonList(String json) {
        if (StrUtil.isBlank(json)) {
            return null;
        }
        try {
            return objectMapper.readValue(json, new TypeReference<List<String>>() {});
        } catch (Exception e) {
            log.warn("JSON 反序列化 List<String> 失败: {}", e.getMessage());
            return null;
        }
    }

    private List<Long> fromJsonLongList(String json) {
        if (StrUtil.isBlank(json)) {
            return null;
        }
        try {
            return objectMapper.readValue(json, new TypeReference<List<Long>>() {});
        } catch (Exception e) {
            log.warn("JSON 反序列化 List<Long> 失败: {}", e.getMessage());
            return null;
        }
    }

    /**
     * v3 激励 credits 每日上限检查（Redis 计数器）
     * <p>仅检查不发奖，creditsAward 调用成功后需调 {@link #confirmAwardQuota} 自增计数器。
     * <p>key: ai:award:{awardTypeLower}:{userId}:{yyyyMMdd}，TTL 25 小时。
     *
     * @return true=可发放（未达上限），false=已达上限
     */
    private boolean tryAcquireAwardQuota(Long userId, String awardType, int dailyLimit) {
        String key = buildAwardQuotaKey(userId, awardType);
        String val = stringRedisTemplate.opsForValue().get(key);
        long current = val == null ? 0L : Long.parseLong(val);
        return current < dailyLimit;
    }

    /**
     * v3 激励 credits 发放确认：自增 Redis 计数器
     * <p>creditsAward 成功后调用；每次自增后都刷新 25 小时 TTL，避免 INCR 成功但 EXPIRE 失败
     * 导致 key 永久存在、用户被永久限制奖励。覆盖式刷新对计数无影响（仅延长 TTL）。
     */
    private void confirmAwardQuota(Long userId, String awardType) {
        String key = buildAwardQuotaKey(userId, awardType);
        stringRedisTemplate.opsForValue().increment(key);
        stringRedisTemplate.expire(key, Duration.ofHours(25));
    }

    private String buildAwardQuotaKey(Long userId, String awardType) {
        String today = LocalDate.now().format(DateTimeFormatter.BASIC_ISO_DATE);
        return "ai:award:" + awardType.toLowerCase() + ":" + userId + ":" + today;
    }

    private AiModelImageFeedbackDTO toFeedbackDTO(AiModelImageFeedback feedback) {
        AiModelImageFeedbackDTO dto = BeanUtils.copyBean(feedback, AiModelImageFeedbackDTO.class);
        if (feedback.getRatingTags() != null) {
            dto.setRatingTags(fromJsonList(feedback.getRatingTags()));
        }
        return dto;
    }
}
