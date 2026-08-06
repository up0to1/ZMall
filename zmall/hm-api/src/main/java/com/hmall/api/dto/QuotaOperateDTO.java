package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * AI 配额确认/回滚请求
 */
@ApiModel(description = "AI 配额确认/回滚请求")
@Data
public class QuotaOperateDTO {

    @ApiModelProperty(value = "配额类型: MODEL / OUTFIT", required = true)
    @NotBlank(message = "配额类型不能为空")
    private String type;

    @ApiModelProperty(value = "配额主体ID", required = true)
    @NotNull(message = "主体ID不能为空")
    private Long id;

    @ApiModelProperty(value = "任务ID", required = true)
    @NotBlank(message = "任务ID不能为空")
    private String taskId;
}
