package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * AI 配额预扣请求
 */
@ApiModel(description = "AI 配额预扣请求")
@Data
public class QuotaDeductDTO {

    @ApiModelProperty(value = "配额类型: MODEL-AI模特(shop_id) / OUTFIT-AI随心搭(user_id)", required = true)
    @NotBlank(message = "配额类型不能为空")
    private String type;

    @ApiModelProperty(value = "配额主体ID（MODEL时为shopId，OUTFIT时为userId）", required = true)
    @NotNull(message = "主体ID不能为空")
    private Long id;

    @ApiModelProperty(value = "任务ID（用于冻结记录关联）", required = true)
    @NotBlank(message = "任务ID不能为空")
    private String taskId;
}
