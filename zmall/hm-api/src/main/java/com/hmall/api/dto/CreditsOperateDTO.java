package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * AI Credits 确认/回滚请求
 *
 * <p>confirm：删除冻结记录（消耗已确认，不返还）。
 * <p>rollback：按冻结明细原路返还（free 返还到原 expireTs 批次，paid 直接累加）。
 */
@ApiModel(description = "AI Credits 确认/回滚请求")
@Data
public class CreditsOperateDTO {

    @ApiModelProperty(value = "配额类型: OUTFIT_RECOMMEND / OUTFIT_VTON", required = true)
    @NotBlank(message = "配额类型不能为空")
    private String type;

    @ApiModelProperty(value = "用户ID", required = true)
    @NotNull(message = "用户ID不能为空")
    private Long userId;

    @ApiModelProperty(value = "任务ID", required = true)
    @NotBlank(message = "任务ID不能为空")
    private String taskId;
}
