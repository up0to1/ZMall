package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * AI 模特任务反馈 DTO（v3 新增，2026-07-20）
 *
 * <p>用于评分接口和拒绝原因接口的返回值，含奖励 credits 数和入池状态。
 */
@ApiModel(description = "AI模特任务反馈")
@Data
public class AiModelImageFeedbackDTO {

    @ApiModelProperty("反馈记录ID")
    private Long id;

    @ApiModelProperty("关联的AI任务ID")
    private String taskId;

    @ApiModelProperty("提交反馈的商家userId")
    private Long userId;

    @ApiModelProperty("反馈类型: RATING(评分) / REJECT(拒绝)")
    private String feedbackType;

    @ApiModelProperty("五星评分（1-5，RATING 时有值）")
    private Integer starRating;

    @ApiModelProperty("评分标签数组")
    private List<String> ratingTags;

    @ApiModelProperty("评分备注")
    private String ratingNote;

    @ApiModelProperty("拒绝原因（REJECT 时有值）")
    private String rejectReason;

    @ApiModelProperty("本次反馈已奖励的 credits 数（0=未奖励）")
    private Integer awardedCredits;

    @ApiModelProperty("是否已入系统模特图池（0=否, 1=是）")
    private Integer savedToPool;

    @ApiModelProperty("创建时间")
    private LocalDateTime createdAt;
}
