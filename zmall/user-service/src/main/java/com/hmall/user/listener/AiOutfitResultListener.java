package com.hmall.user.listener;

import com.hmall.api.dto.AiOutfitResultMessage;
import com.hmall.common.constants.MqConstants;
import com.hmall.user.enums.QuotaType;
import com.hmall.user.metrics.UserAiMetrics;
import com.hmall.user.service.ICreditsService;
import com.hmall.user.service.IQuotaService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.core.ExchangeTypes;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.amqp.rabbit.annotation.Exchange;
import org.springframework.amqp.rabbit.annotation.Queue;
import org.springframework.amqp.rabbit.annotation.QueueBinding;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import java.time.Duration;

/**
 * AI 随心搭结果回流监听器
 *
 * <p>Python ai-models / ai-outfit 完成生成后，向 ai.outfit.exchange 发送结果消息。
 * user-service 消费该消息，按 {@code phase} 字段路由到不同的配额服务：
 *
 * <ul>
 *   <li>{@code phase=null}（旧版商品驱动）→ {@link IQuotaService} 次数制 confirm/rollback</li>
 *   <li>{@code phase=candidate/vton}（v3 阶段一/二）→ {@link ICreditsService} credits 积分制 confirm/rollback</li>
 * </ul>
 *
 * <p>v3.1 失败规则（Python 侧 _async_vton 做权威判定，Java 侧按 status 二分）：
 * <ul>
 *   <li>阶段一失败（candidate phase + FAILED）→ credits rollback 全额退还</li>
 *   <li>阶段二 VTON 部分失败（vton phase + SUCCESS，Python 侧已判定部分失败不退还）→ credits confirm</li>
 *   <li>阶段二 VTON 全部失败 / API 故障（vton phase + FAILED）→ credits rollback 全额退还</li>
 * </ul>
 *
 * <p>幂等保障（与 item-service 的 AiModelResultListener 对齐）：
 * <ul>
 *   <li>Redis SETNX（ai:task:outfit:result:{taskId}，TTL 1h）防并发消费同一消息</li>
 *   <li>IQuotaService/ICreditsService 内部冻结记录存在性检查（not_found 时静默跳过）</li>
 * </ul>
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AiOutfitResultListener {

    private final IQuotaService quotaService;
    private final ICreditsService creditsService;
    private final StringRedisTemplate stringRedisTemplate;
    private final UserAiMetrics userAiMetrics;

    /** 旧版 OUTFIT 配额类型（商品驱动模式） */
    private static final String QUOTA_TYPE_OUTFIT = "OUTFIT";
    /** MQ 队列名（用于监控标签） */
    private static final String QUEUE_NAME = MqConstants.AI_OUTFIT_RESULT_QUEUE;

    @RabbitListener(bindings = @QueueBinding(
            value = @Queue(name = MqConstants.AI_OUTFIT_RESULT_QUEUE, durable = "true"),
            exchange = @Exchange(name = MqConstants.AI_OUTFIT_EXCHANGE, type = ExchangeTypes.TOPIC),
            key = MqConstants.AI_OUTFIT_RESULT_KEY
    ))
    public void listenOutfitResult(AiOutfitResultMessage message) {
        log.info("收到 AI 随心搭结果消息: taskId={}, userId={}, type={}, phase={}, status={}",
                message.getTaskId(), message.getUserId(), message.getType(),
                message.getPhase(), message.getStatus());

        String taskId = message.getTaskId();
        Long userId = message.getUserId();

        if (taskId == null || taskId.isBlank()) {
            log.warn("收到空 taskId 的随心搭结果消息，丢弃");
            userAiMetrics.recordMqConsumeFailure(QUEUE_NAME);
            return;
        }
        if (userId == null) {
            log.warn("收到空 userId 的随心搭结果消息，丢弃: taskId={}", taskId);
            userAiMetrics.recordMqConsumeFailure(QUEUE_NAME);
            return;
        }

        // 1. 幂等校验：Redis SETNX（防并发消费同一消息导致配额双重确认/回滚）
        String idempotentKey = "ai:task:outfit:result:" + taskId;
        Boolean acquired = stringRedisTemplate.opsForValue()
                .setIfAbsent(idempotentKey, "1", Duration.ofHours(1));
        if (Boolean.FALSE.equals(acquired)) {
            log.info("Redis 幂等标记已存在，跳过: taskId={}", taskId);
            userAiMetrics.recordQuotaOperation(resolveQuotaTypeForMetrics(message), "idempotent_skip");
            return;
        }

        // 2. 按 phase 路由到不同的配额服务
        try {
            String phase = message.getPhase();
            if (phase == null || phase.isBlank()) {
                // 旧版商品驱动模式 → 次数制
                handleLegacyQuota(message);
            } else if ("candidate".equals(phase)) {
                // v3 阶段一 → credits 制
                handleCreditsCandidate(message);
            } else if ("vton".equals(phase)) {
                // v3 阶段二 → credits 制（含部分失败规则）
                handleCreditsVton(message);
            } else {
                log.warn("未知 phase，跳过配额操作: taskId={}, phase={}", taskId, phase);
            }
        } catch (Exception e) {
            log.warn("配额操作异常（可能已处理）: taskId={}, userId={}, error={}",
                    taskId, userId, e.getMessage());
            userAiMetrics.recordQuotaOperation(resolveQuotaTypeForMetrics(message), "failed");
            // 不抛异常，让 MQ ack 确认（避免无限重投）；失败由监控告警人工补救
        }
    }

    /**
     * 旧版次数制配额处理（商品驱动模式）
     */
    private void handleLegacyQuota(AiOutfitResultMessage message) {
        String taskId = message.getTaskId();
        Long userId = message.getUserId();
        if ("SUCCESS".equals(message.getStatus())) {
            quotaService.confirm(QUOTA_TYPE_OUTFIT, userId, taskId);
            log.info("旧版配额确认成功: taskId={}, userId={}", taskId, userId);
            userAiMetrics.recordQuotaOperation(QUOTA_TYPE_OUTFIT, "confirm");
        } else {
            quotaService.rollback(QUOTA_TYPE_OUTFIT, userId, taskId);
            log.info("旧版配额回滚成功: taskId={}, userId={}", taskId, userId);
            userAiMetrics.recordQuotaOperation(QUOTA_TYPE_OUTFIT, "rollback");
        }
    }

    /**
     * v3 阶段一候选推荐 credits 处理
     */
    private void handleCreditsCandidate(AiOutfitResultMessage message) {
        String taskId = message.getTaskId();
        Long userId = message.getUserId();
        if ("SUCCESS".equals(message.getStatus())) {
            creditsService.confirm(QuotaType.OUTFIT_RECOMMEND, userId, taskId);
            log.info("v3 阶段一 credits 确认成功: taskId={}, userId={}", taskId, userId);
            userAiMetrics.recordQuotaOperation(QuotaType.OUTFIT_RECOMMEND.getValue(), "confirm");
        } else {
            // 阶段一失败：全额回滚
            creditsService.rollback(QuotaType.OUTFIT_RECOMMEND, userId, taskId);
            log.info("v3 阶段一 credits 回滚成功: taskId={}, userId={}", taskId, userId);
            userAiMetrics.recordQuotaOperation(QuotaType.OUTFIT_RECOMMEND.getValue(), "rollback");
        }
    }

    /**
     * v3 阶段二 VTON 生成 credits 处理
     *
     * <p>v3.1 失败规则（Python 侧 _async_vton 已做完整判定，Java 侧按 status 二分）：
     * <ul>
     *   <li>SUCCESS（含部分失败）→ confirm（部分失败不退还 credits，由 Python 侧判定后推 SUCCESS）</li>
     *   <li>FAILED（全部失败 / VTON API 故障）→ rollback 全额退还</li>
     * </ul>
     *
     * <p>注：Python 侧 _async_vton 在部分失败时走 _on_success 发 SUCCESS，在全部失败/API 故障时
     * 走 _on_failure 发 FAILED。Java 侧无需重复判定 partialFailures 字段（Python 已做权威判定）。
     */
    private void handleCreditsVton(AiOutfitResultMessage message) {
        String taskId = message.getTaskId();
        Long userId = message.getUserId();

        if ("SUCCESS".equals(message.getStatus())) {
            // 阶段二成功（含部分失败，部分失败不退还 credits）→ confirm
            creditsService.confirm(QuotaType.OUTFIT_VTON, userId, taskId);
            log.info("v3 阶段二 credits 确认成功: taskId={}, userId={}", taskId, userId);
            userAiMetrics.recordQuotaOperation(QuotaType.OUTFIT_VTON.getValue(), "confirm");
        } else {
            // 全部失败 / VTON API 故障 → rollback 全额退还
            creditsService.rollback(QuotaType.OUTFIT_VTON, userId, taskId);
            log.info("v3 阶段二 credits 全额回滚: taskId={}, userId={}, errorMsg={}",
                    taskId, userId, message.getErrorMsg());
            userAiMetrics.recordQuotaOperation(QuotaType.OUTFIT_VTON.getValue(), "rollback");
        }
    }

    /**
     * 根据 phase 解析监控标签
     */
    private String resolveQuotaTypeForMetrics(AiOutfitResultMessage message) {
        String phase = message.getPhase();
        if (phase == null || phase.isBlank()) {
            return QUOTA_TYPE_OUTFIT;
        }
        if ("candidate".equals(phase)) {
            return QuotaType.OUTFIT_RECOMMEND.getValue();
        }
        if ("vton".equals(phase)) {
            return QuotaType.OUTFIT_VTON.getValue();
        }
        return "UNKNOWN";
    }
}
