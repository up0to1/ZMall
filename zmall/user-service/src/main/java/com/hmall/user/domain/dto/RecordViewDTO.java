package com.hmall.user.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * 记录浏览请求 DTO
 */
@Data
@ApiModel(description = "记录浏览请求参数")
public class RecordViewDTO {

    @ApiModelProperty("商品ID")
    private Long itemId;

    @ApiModelProperty("浏览来源：search/recommend/ai_outfit/shop/direct")
    private String viewSource;

    @ApiModelProperty("停留时长（秒）")
    private Integer viewDuration;
}
