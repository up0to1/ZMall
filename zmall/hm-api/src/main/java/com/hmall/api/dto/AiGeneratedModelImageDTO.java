package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;
import javax.validation.constraints.Size;
import java.util.List;

/**
 * AI 生成模特图入库请求 DTO（v3 新增，2026-07-20）
 *
 * <p>用于 AI 随心搭场景 A 兜底（Python 调 Qwen/可灵 AI 生成契合穿搭的模特图后入库）。
 */
@ApiModel(description = "AI生成模特图入库请求")
@Data
public class AiGeneratedModelImageDTO {

    @ApiModelProperty(value = "模特图 URL（相对路径或完整 URL）", required = true)
    @NotBlank(message = "imageUrl 不能为空")
    private String imageUrl;

    @ApiModelProperty(value = "来源：1=AI任务后保存（≥3★）/ 3=AI自动生成", required = true)
    @NotNull(message = "source 不能为空")
    private Integer source;

    @ApiModelProperty("性别（可空）：male/female")
    private String gender;

    @ApiModelProperty("肤色（可空）：fair/wheat/dark")
    private String skinTone;

    @ApiModelProperty("风格标签（可空）")
    private List<String> styleTags;

    @ApiModelProperty("备注（可空，≤128字）")
    @Size(max = 128, message = "备注最长 128 字")
    private String note;
}
