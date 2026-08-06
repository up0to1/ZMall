package com.hmall.item.metrics;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Tags;
import io.micrometer.core.instrument.Timer;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import javax.annotation.PostConstruct;
import java.time.Duration;

/**
 * AI 业务监控指标定义（后端架构方案 §7.5 监控告警）
 *
 * 暴露给 Prometheus 的指标：
 *   1. ai_task_total{type, status}            - AI 任务计数器（按类型和状态）
 *   2. ai_task_duration_seconds{type}         - AI 任务耗时直方图（P95 监控）
 *   3. ai_quota_operation_total{type, result} - 配额操作计数（确认/回滚）
 *   4. ai_timeout_compensation_total          - 超时补偿次数
 *   5. ai_mq_consume_failure_total{queue}     - MQ 消费失败次数
 *
 * 告警阈值参考：
 *   - ai_task_duration_seconds_quantile{quantile="0.95"} > 5s
 *   - ai_task_total{status="FAILED"} 占比 > 5%
 *   - ai_timeout_compensation_total 增长过快
 */
@Slf4j
@Component
public class AiMetrics {

    private final MeterRegistry meterRegistry;

    @Autowired
    public AiMetrics(MeterRegistry meterRegistry) {
        this.meterRegistry = meterRegistry;
    }

    @PostConstruct
    public void init() {
        log.info("AI 业务监控指标已初始化: registry={}", meterRegistry.getClass().getSimpleName());
    }

    /**
     * 记录 AI 任务完成（成功/失败/超时）
     *
     * @param taskType 任务类型（MODEL / OUTFIT_AGENT / OUTFIT_PRODUCT）
     * @param status   终态（SUCCESS / FAILED / TIMEOUT）
     */
    public void recordTaskComplete(String taskType, String status) {
        try {
            Counter.builder("ai_task_total")
                    .description("AI 任务总数（按类型与终态）")
                    .tags(Tags.of("type", taskType, "status", status))
                    .register(meterRegistry)
                    .increment();
        } catch (Exception e) {
            log.warn("记录任务计数失败: type={}, status={}, error={}", taskType, status, e.getMessage());
        }
    }

    /**
     * 记录 AI 任务耗时（用于 P95 计算）
     *
     * @param taskType 任务类型
     * @param costMs   耗时毫秒
     */
    public void recordTaskDuration(String taskType, long costMs) {
        try {
            Timer.builder("ai_task_duration_seconds")
                    .description("AI 任务耗时分布（P95 监控）")
                    .tag("type", taskType)
                    .sla(Duration.ofSeconds(1), Duration.ofSeconds(5), Duration.ofSeconds(10), Duration.ofSeconds(30))
                    .register(meterRegistry)
                    .record(Duration.ofMillis(costMs));
        } catch (Exception e) {
            log.warn("记录任务耗时失败: type={}, costMs={}, error={}", taskType, costMs, e.getMessage());
        }
    }

    /**
     * 记录配额操作（确认/回滚）
     *
     * @param quotaType 配额类型（MODEL / OUTFIT_AGENT）
     * @param result    操作结果（confirm / rollback / failed）
     */
    public void recordQuotaOperation(String quotaType, String result) {
        try {
            Counter.builder("ai_quota_operation_total")
                    .description("AI 配额操作总数（确认/回滚/失败）")
                    .tags(Tags.of("type", quotaType, "result", result))
                    .register(meterRegistry)
                    .increment();
        } catch (Exception e) {
            log.warn("记录配额操作失败: type={}, result={}, error={}", quotaType, result, e.getMessage());
        }
    }

    /**
     * 记录超时补偿次数
     */
    public void recordTimeoutCompensation() {
        try {
            Counter.builder("ai_timeout_compensation_total")
                    .description("AI 任务超时补偿次数")
                    .register(meterRegistry)
                    .increment();
        } catch (Exception e) {
            log.warn("记录超时补偿失败: error={}", e.getMessage());
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
