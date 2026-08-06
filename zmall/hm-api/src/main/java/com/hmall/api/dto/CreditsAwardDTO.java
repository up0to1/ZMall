package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.Min;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * AI Credits 激励奖励请求（US-AT-46/47）
 *
 * <p>奖励场景：
 * <ul>
 *   <li>商家评分 ≥4★ + 发布到商品详情 → 奖 1 credit（每日上限 5 次）</li>
 *   <li>商家详细填写拒绝原因 ≥20 字 → 奖 1 credit（每日上限 3 次）</li>
 * </ul>
 *
 * <p>调用方：item-service 在 publishModelImage / submitModelRejectReason 完成后异步调 /credits/award
 */
@ApiModel(description = "AI Credits 激励奖励请求")
@Data
public class CreditsAwardDTO {

    @ApiModelProperty(value = "用户ID", required = true)
    @NotNull(message = "用户ID不能为空")
    private Long userId;

    @ApiModelProperty(value = "奖励 credits 数", required = true)
    @NotNull(message = "奖励 credits 数不能为空")
    @Min(value = 1, message = "奖励 credits 数必须大于 0")
    private Integer credits;

    @ApiModelProperty(value = "奖励类型: RATING_PUBLISH / REJECT_REASON", required = true)
    @NotBlank(message = "奖励类型不能为空")
    private String awardType;

    @ApiModelProperty(value = "关联的业务ID（如 taskId/modelImageId），用于审计")
    private String bizRefId;
}
