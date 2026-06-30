package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "评价提交DTO")
public class CommentCreateDTO {

    @ApiModelProperty("商品ID")
    private Long itemId;

    @ApiModelProperty("订单ID")
    private Long orderId;

    @ApiModelProperty("评价内容")
    private String content;

    @ApiModelProperty("评分1-5")
    private Integer rating;

    @ApiModelProperty("图片URL列表，JSON数组")
    private String images;
}