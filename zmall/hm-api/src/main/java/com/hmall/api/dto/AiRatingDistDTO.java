package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * AI 模特图评分分布 DTO（按星级聚合，阶段一：AI 模特图指标）
 */
@Data
@ApiModel(description = "AI评分分布")
public class AiRatingDistDTO {

    @ApiModelProperty("星级 1-5")
    private int star;

    @ApiModelProperty("该星级评分数")
    private long count;
}
