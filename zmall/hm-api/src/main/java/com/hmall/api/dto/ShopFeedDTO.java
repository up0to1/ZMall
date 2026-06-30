package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@ApiModel(description = "商家推送动态DTO")
public class ShopFeedDTO {

    @ApiModelProperty("动态ID")
    private Long id;

    @ApiModelProperty("商家ID")
    private Long shopId;

    @ApiModelProperty("发布者用户ID")
    private Long userId;

    @ApiModelProperty("关联商品ID")
    private Long itemId;

    @ApiModelProperty("推送内容正文")
    private String content;

    @ApiModelProperty("图片URL列表，JSON数组格式")
    private String images;

    @ApiModelProperty("点赞数")
    private Integer liked;

    @ApiModelProperty("发布时间")
    private LocalDateTime createTime;
}