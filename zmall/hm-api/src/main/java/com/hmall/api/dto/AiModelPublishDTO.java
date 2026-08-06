package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * AI 模特图发布请求
 *
 * 商家在任务列表中选定一张模特图后，调此接口写回商品主图字段。
 */
@ApiModel(description = "AI 模特图发布请求")
@Data
public class AiModelPublishDTO {

    @ApiModelProperty(value = "任务ID", required = true)
    @NotBlank(message = "任务ID不能为空")
    private String taskId;

    @ApiModelProperty(value = "商品ID", required = true)
    @NotNull(message = "商品ID不能为空")
    private Long itemId;

    @ApiModelProperty(value = "选定的模特图 OSS URL", required = true)
    @NotBlank(message = "图片URL不能为空")
    private String imageUrl;
}
