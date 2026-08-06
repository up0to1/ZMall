package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.Max;
import javax.validation.constraints.Min;
import javax.validation.constraints.NotNull;
import java.util.List;

/**
 * AI 模特任务评分请求 DTO（v3 新增，2026-07-20）
 */
@ApiModel(description = "AI模特任务评分请求")
@Data
public class AiModelRatingDTO {

    @ApiModelProperty(value = "五星评分（1-5）", required = true)
    @NotNull(message = "评分不能为空")
    @Min(value = 1, message = "评分最低1星")
    @Max(value = 5, message = "评分最高5星")
    private Integer starRating;

    @ApiModelProperty("评分标签数组（如 [\"质感好\",\"比例协调\"]）")
    private List<String> ratingTags;

    @ApiModelProperty("评分备注（≤256字）")
    private String ratingNote;

    @ApiModelProperty(value = "是否同意将最终图入系统模特图池（true 时 ≥3★ 自动入池）", required = true)
    @NotNull(message = "saveToPool 不能为空")
    private Boolean saveToPool;
}
