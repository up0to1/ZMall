package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * AI 任务趋势 DTO（按天聚合，阶段一：AI 模特图指标）
 */
@Data
@ApiModel(description = "AI任务趋势")
public class AiTaskTrendDTO {

    @ApiModelProperty("日期（yyyy-MM-dd）")
    private String date;

    @ApiModelProperty("当日任务总数")
    private long total;

    @ApiModelProperty("当日成功数")
    private long success;

    @ApiModelProperty("当日失败数（含 FAILED/TIMEOUT）")
    private long failed;

    @ApiModelProperty("当日平均耗时（毫秒，仅成功任务）")
    private long avgCostMs;
}
