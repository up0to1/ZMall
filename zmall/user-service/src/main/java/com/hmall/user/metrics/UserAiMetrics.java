package com.hmall.user.metrics;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Tags;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;

/**
 * user-service 侧 AI 配额监控指标（后端架构方案 §7.5 监控告警）
 *
 * 与 item-service 的 AiMetrics 对应，但只关注 OUTFIT 配额操作（user-service 消费
 * ai.outfit.exchange 的结果消息做配额确认/回滚）。
 *
 * 暴露给 Prometheus 的指标：
 *   1. ai_quota_operation_total{type, result}  - 配额操作计数（confirm/rollback/failed/idempotent_skip）
 *   2. ai_mq_consume_failure_total{queue}      - MQ 消费失败次数
 *
 * 告警阈值参考：
 *   - ai_quota_operation_total{result="failed"} 增长 → user-service 不可用或 Redis 异常
 *   - ai_mq_consume_failure_total 增长 → MQ 消费异常
 */
@Slf4j
@Component
public class UserAiMetrics {

    private final MeterRegistry meterRegistry;

    @Autowired
    public UserAiMetrics(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
    }

    @PostConstruct
    public void init() {
        log.info("user-service AI 配额监控指标已初始化: registry={}", meterRegistry.getClass().getSimpleName());
    }

    /**
     * 记录配额操作（确认/回滚/失败/幂等跳过）
     *
     * @param quotaType 配额类型（OUTFIT）
     * @param result    操作结果（confirm / rollback / failed / idempotent_skip）
     */
    public void recordQuotaOperation(String quotaType, String result) {
        try {
            Counter.builder("ai_quota_operation_total")
                    .description("AI 配额操作总数（确认/回滚/失败/幂等跳过）")
                    .tags(Tags.of("type", quotaType, "result", result))
                    .register(meterRegistry)
                    .increment();
        } catch (Exception e) {
            log.warn("记录配额操作失败: type={}, result={}, error={}", quotaType, result, e.getMessage());
        }
    }

    /**
     * 记录 MQ 消费失败
     *
     * @param queue 队列名
     */
    public void recordMqConsumeFailure(String queue) {
        try {
            Counter.builder("ai_mq_consume_failure_total")
                    .description("AI MQ 消费失败次数")
                    .tag("queue", queue)
                    .register(meterRegistry)
                    .increment();
        } catch (Exception e) {
            log.warn("记录 MQ 消费失败: queue={}, error={}", queue, e.getMessage());
        }
    }
}
