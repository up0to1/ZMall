package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Size;

/**
 * AI 模特任务拒绝原因请求 DTO（v3 新增，2026-07-20）
 */
@ApiModel(description = "AI模特任务拒绝原因请求")
@Data
public class AiModelRejectDTO {

    @ApiModelProperty(value = "拒绝原因（≥20 字可奖励 1 credit）", required = true)
    @NotBlank(message = "拒绝原因不能为空")
    @Size(max = 512, message = "拒绝原因最长 512 字")
    private String rejectReason;
}
