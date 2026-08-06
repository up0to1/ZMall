package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * AI 模特图统计概览 DTO（商家维度，阶段一：AI 模特图指标）
 *
 * <p>对应 ai_task 表（shop_id + task_type=MODEL）与 ai_model_image_feedback 表（shop_id）的聚合结果。
 */
@Data
@ApiModel(description = "AI模特图统计概览")
public class AiModelStatsDTO {

    @ApiModelProperty("累计任务总数")
    private long taskTotal;

    @ApiModelProperty("今日新增任务数")
    private long taskToday;

    @ApiModelProperty("成功任务数")
    private long successCount;

    @ApiModelProperty("失败任务数（含 FAILED/TIMEOUT）")
    private long failedCount;

    @ApiModelProperty("处理中任务数")
    private long processingCount;

    @ApiModelProperty("待处理任务数")
    private long pendingCount;

    @ApiModelProperty("成功率（0-1，= successCount / taskTotal）")
    private double successRate;

    @ApiModelProperty("平均耗时（毫秒，仅成功任务）")
    private long avgCostMs;

    @ApiModelProperty("已发布到主图数")
    private long publishedCount;

    @ApiModelProperty("发布转化率（0-1，= publishedCount / successCount）")
    private double publishRate;

    @ApiModelProperty("平均评分（1-5）")
    private double avgRating;

    @ApiModelProperty("评分数")
    private long ratingCount;

    @ApiModelProperty("拒绝次数")
    private long rejectCount;

    @ApiModelProperty("拒绝率（0-1，= rejectCount / (ratingCount + rejectCount)）")
    private double rejectRate;

    @ApiModelProperty("入池数（saved_to_pool=1）")
    private long poolCount;
}
