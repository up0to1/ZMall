package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "商家回复评价DTO")
public class CommentReplyDTO {

    @ApiModelProperty("回复内容")
    private String reply;
}