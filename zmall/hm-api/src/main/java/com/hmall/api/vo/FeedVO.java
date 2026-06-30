package com.hmall.api.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "Feed动态视图")
public class FeedVO {
    @ApiModelProperty("动态ID")
    private Long id;
    @ApiModelProperty("商家ID")
    private Long shopId;
    @ApiModelProperty("用户ID")
    private Long userId;
    @ApiModelProperty("商品ID")
    private Long itemId;
    @ApiModelProperty("内容")
    private String content;
    @ApiModelProperty("图片")
    private String images;
    @ApiModelProperty("点赞数")
    private Integer liked;
    @ApiModelProperty("创建时间")
    private String createTime;
    @ApiModelProperty("商家名称")
    private String shopName;
    @ApiModelProperty("商家Logo")
    private String shopLogo;
    @ApiModelProperty("Redis中的时间戳score，用于滚动分页")
    private Double score;
}
