package com.hmall.api.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "评价视图")
public class CommentVO {

    @ApiModelProperty("评价ID")
    private Long id;

    @ApiModelProperty("商品ID")
    private Long itemId;

    @ApiModelProperty("商品名称")
    private String itemName;

    @ApiModelProperty("订单ID")
    private Long orderId;

    @ApiModelProperty("用户ID")
    private Long userId;

    @ApiModelProperty("评价内容")
    private String content;

    @ApiModelProperty("评分1-5")
    private Integer rating;

    @ApiModelProperty("图片")
    private String images;

    @ApiModelProperty("商家回复")
    private String reply;

    @ApiModelProperty("回复时间")
    private String replyTime;

    @ApiModelProperty("是否隐藏 0-显示 1-隐藏")
    private Integer isHidden;

    @ApiModelProperty("评价时间")
    private String createTime;
}
