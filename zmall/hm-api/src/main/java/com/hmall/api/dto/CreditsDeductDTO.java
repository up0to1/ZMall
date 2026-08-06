package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.Min;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * AI Credits 预扣请求（v3 积分制）
 *
 * <p>调用方根据 v3 阶段传入：
 * <ul>
 *   <li>阶段一候选推荐：type=OUTFIT_RECOMMEND, credits=2</li>
 *   <li>阶段二 VTON 生成：type=OUTFIT_VTON, credits=5×N（N=用户选定的套装数）</li>
 * </ul>
 *
 * <p>FIFO 扣减：先扣赠送 credits（30 天有效期，按到期升序），不足部分扣充值 credits（永久）。
 * 扣减明细写入 Redis frozenKey，rollback 时按原路返还。
 */
@ApiModel(description = "AI Credits 预扣请求")
@Data
public class CreditsDeductDTO {

    @ApiModelProperty(value = "配额类型: OUTFIT_RECOMMEND / OUTFIT_VTON", required = true)
    @NotBlank(message = "配额类型不能为空")
    private String type;

    @ApiModelProperty(value = "用户ID", required = true)
    @NotNull(message = "用户ID不能为空")
    private Long userId;

    @ApiModelProperty(value = "任务ID（用于冻结记录关联）", required = true)
    @NotBlank(message = "任务ID不能为空")
    private String taskId;

    @ApiModelProperty(value = "本次需要扣减的 credits 数（阶段一=2，阶段二=5×N）", required = true)
    @NotNull(message = "credits 数不能为空")
    @Min(value = 1, message = "credits 数必须大于 0")
    private Integer credits;

    @ApiModelProperty(value = "阶段标识（candidate/vton），用于冻结明细和审计")
    private String phase;
}
