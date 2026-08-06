package com.hmall.item.schedule;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.hmall.api.client.QuotaClient;
import com.hmall.api.dto.CreditsOperateDTO;
import com.hmall.api.dto.QuotaOperateDTO;
import com.hmall.common.constants.MqConstants;
import com.hmall.item.domain.po.AiTask;
import com.hmall.item.metrics.AiMetrics;
import com.hmall.item.service.IAiTaskService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;

/**
 * AI 任务超时补偿定时任务
 *
 * 设计文档 §7.3 超时补偿：
 *   - ai_task 表中 status=PROCESSING 且 created_at 距今 > 5min 的记录
 *   - 标记为 TIMEOUT
 *   - 调用 QuotaClient.rollback 回滚预扣的配额
 *   - 写 Redis 幂等标记，避免后续 MQ 结果消息重复处理
 *
 * 扫描间隔：60 秒（避免对 DB 压力过大）
 * 超时阈值：11 分钟（与 Python 侧 model_consumer.py future.result(timeout=600) 对齐）
 *
 * 并发安全：
 *   使用条件更新 WHERE status IN ('PENDING','PROCESSING') 避免与 MQ 结果回流竞态：
 *   如果 MQ 结果在扫描和更新之间到达并把状态改为 SUCCESS/FAILED，条件更新会返回 0 行，
 *   跳过该任务，避免把 SUCCESS 覆盖为 TIMEOUT 导致配额双重操作（先 confirm 再 rollback）。
 *
 * P1-7 修复：原 5min 阈值与 Python 600s（10min）超时不匹配，Python 在 5-10min 区间
 * 正常处理时会被 Java 误判超时回滚配额，导致模特图生成成功但 ai_task=TIMEOUT、配额已回滚、
 * 前端拿不到 resultUrls。修复为 11min（Python 600s + 1min 兜底余量）。
 * OUTFIT_AGENT 链路因 LangGraph ASYNC_TIMEOUT=30s 远小于 11min，不受影响。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AiTaskTimeoutScheduler {

    private final IAiTaskService aiTaskService;
    private final QuotaClient quotaClient;
    private final StringRedisTemplate stringRedisTemplate;
    private final AiMetrics aiMetrics;

    /** 超时阈值：11 分钟（P1-7 修复：对齐 Python model_consumer 600s 超时 + 1min 兜底） */
    private static final long TIMEOUT_THRESHOLD_MINUTES = 11L;

    /** 幂等标记 TTL：1 小时 */
    private static final long IDEMPOTENT_TTL_HOURS = 1L;

    /**
     * 配额类型常量（与 user-service QuotaType 枚举保持一致）
     * 注意：task_type（任务类型）与 quota_type（配额类型）是两个不同概念
     *   - task_type: MODEL / OUTFIT_AGENT / OUTFIT_PRODUCT
     *   - quota_type: MODEL / OUTFIT（QuotaType 枚举只认这两个值）
     * 此前错误地返回 "OUTFIT_AGENT" 导致 QuotaType.of() 抛 BadRequestException。
     */
    private static final String QUOTA_TYPE_MODEL = "MODEL";
    private static final String QUOTA_TYPE_OUTFIT = "OUTFIT";

    /**
     * 每 60 秒扫描一次 ai_task 表，处理超时任务
     */
    @Scheduled(fixedDelay = 60 * 1000L)
    public void scanTimeoutTasks() {
        LocalDateTime threshold = LocalDateTime.now().minusMinutes(TIMEOUT_THRESHOLD_MINUTES);

        // 查询 PENDING/PROCESSING 且创建时间早于阈值的任务
        LambdaQueryWrapper<AiTask> wrapper = new LambdaQueryWrapper<AiTask>()
                .in(AiTask::getStatus, "PENDING", "PROCESSING")
                .lt(AiTask::getCreatedAt, threshold)
                .last("LIMIT 200"); // 单次最多处理 200 条，避免长时间锁表
        List<AiTask> timeoutTasks = aiTaskService.list(wrapper);

        if (timeoutTasks.isEmpty()) {
            return;
        }

        log.warn("发现 {} 个超时 AI 任务，开始补偿处理", timeoutTasks.size());
        int successCount = 0;
        int failCount = 0;

        for (AiTask task : timeoutTasks) {
            try {
                handleTimeoutTask(task);
                successCount++;
            } catch (Exception e) {
                failCount++;
                log.error("超时任务补偿异常: taskId={}, error={}", task.getTaskId(), e.getMessage(), e);
            }
        }

        log.warn("超时任务补偿完成: 成功={}, 失败={}", successCount, failCount);
    }

    /**
     * 处理单个超时任务：
     *   1. 条件更新 ai_task.status = TIMEOUT（WHERE status IN ('PENDING','PROCESSING')）
     *   2. 回滚配额
     *   3. 写 Redis 幂等标记（防后续 MQ 结果消息重复处理）
     */
    private void handleTimeoutTask(AiTask task) {
        String taskId = task.getTaskId();
        LocalDateTime now = LocalDateTime.now();
        long costMs = task.getCreatedAt() != null
                ? Duration.between(task.getCreatedAt(), now).toMillis() : 0L;

        // 1.条件更新任务状态为 TIMEOUT
        // 修复：使用 LambdaUpdateWrapper 加 WHERE status IN ('PENDING','PROCESSING') 条件，
        // 避免 MQ 结果回流后把 SUCCESS/FAILED 覆盖为 TIMEOUT 导致配额双重操作
        LambdaUpdateWrapper<AiTask> updateWrapper = new LambdaUpdateWrapper<AiTask>()
                .eq(AiTask::getId, task.getId())
                .in(AiTask::getStatus, "PENDING", "PROCESSING")
                .set(AiTask::getStatus, "TIMEOUT")
                .set(AiTask::getFinishedAt, now)
                .set(AiTask::getCostMs, (int) costMs)
                .set(AiTask::getErrorMsg, "任务超时（超过 " + TIMEOUT_THRESHOLD_MINUTES + " 分钟未完成）");
        boolean updated = aiTaskService.update(updateWrapper);

        if (!updated) {
            // 状态已变更（MQ 结果先到达），跳过该任务，避免覆盖 SUCCESS/FAILED
            log.info("任务状态已变更，跳过超时处理: taskId={}, originalStatus={}", taskId, task.getStatus());
            return;
        }

        log.info("AI 任务已标记超时: taskId={}, originalStatus={}, costMs={}",
                taskId, task.getStatus(), costMs);

        // 1.1 业务监控指标埋点
        aiMetrics.recordTimeoutCompensation();
        aiMetrics.recordTaskComplete(task.getTaskType(), "TIMEOUT");
        aiMetrics.recordTaskDuration(task.getTaskType(), costMs);

        // 2.回滚配额（按 taskType 区分配额类型）
        // P1-10 修复：MODEL 类型已迁移到 v3 credits 制，走 /credits/rollback；
        //             OUTFIT 类型仍走旧版 /quota/rollback 次数制。
        Long shopId = task.getShopId() != null ? task.getShopId() : task.getUserId();
        if (shopId == null) {
            log.warn("超时任务缺少 shopId/userId，跳过配额回滚: taskId={}", taskId);
            return;
        }
        String quotaType = resolveQuotaType(task.getTaskType());
        try {
            if (QUOTA_TYPE_MODEL.equals(quotaType)) {
                // P1-10：MODEL 走 credits 回滚（商家维度 shopId = userId）
                CreditsOperateDTO creditsDTO = new CreditsOperateDTO();
                creditsDTO.setType(quotaType);
                creditsDTO.setUserId(shopId);
                creditsDTO.setTaskId(taskId);
                quotaClient.creditsRollback(creditsDTO);
            } else {
                // OUTFIT 仍走旧版次数制回滚
                QuotaOperateDTO operateDTO = new QuotaOperateDTO();
                operateDTO.setType(quotaType);
                operateDTO.setId(shopId);
                operateDTO.setTaskId(taskId);
                quotaClient.rollback(operateDTO);
            }
            log.info("超时任务配额已回滚: taskId={}, shopId={}, type={}", taskId, shopId, quotaType);
            aiMetrics.recordQuotaOperation(quotaType, "rollback");
        } catch (Exception e) {
            // 配额回滚失败仅日志记录——注意：本任务 status 已置为 TIMEOUT，
            // 下次扫描不会再次命中（条件 WHERE status IN PENDING/PROCESSING），
            // 因此配额泄漏风险存在，依赖监控告警人工补救（对账脚本可参考 reconcile_mysql_qdrant.py 模式）。
            log.error("超时任务配额回滚失败（配额可能泄漏，需人工对账）: taskId={}, shopId={}, type={}, error={}",
                    taskId, shopId, quotaType, e.getMessage());
            aiMetrics.recordQuotaOperation(quotaType, "failed");
        }

        // 3.写 Redis 幂等标记（防 MQ 延迟到达的结果消息触发重复处理）
        String idempotentKey = MqConstants.AI_TASK_RESULT_IDEMPOTENT_PREFIX + taskId;
        try {
            stringRedisTemplate.opsForValue()
                    .set(idempotentKey, "TIMEOUT", Duration.ofHours(IDEMPOTENT_TTL_HOURS));
        } catch (Exception e) {
            log.warn("写幂等标记失败（不影响主流程）: taskId={}, error={}", taskId, e.getMessage());
        }
    }

    /**
     * 根据 taskType 解析配额类型（注意 task_type ≠ quota_type）
     *   - task_type=MODEL         → quota_type=MODEL
     *   - task_type=OUTFIT_AGENT  → quota_type=OUTFIT（共用随心搭配额）
     *   - task_type=OUTFIT_PRODUCT → quota_type=OUTFIT（共用随心搭配额）
     *   - task_type=null 或未知    → quota_type=OUTFIT（保守默认，避免 null 导致 QuotaType.of() 抛异常）
     *
     * 修复：此前返回 "OUTFIT_AGENT"，但 user-service QuotaType 枚举只认 "OUTFIT"，
     * 导致 QuotaType.of("OUTFIT_AGENT") 抛 BadRequestException。
     */
    private String resolveQuotaType(String taskType) {
        if ("MODEL".equals(taskType)) {
            return QUOTA_TYPE_MODEL;
        }
        return QUOTA_TYPE_OUTFIT;
    }
}
