package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "商品销量排行")
public class TopItemDTO {
    @ApiModelProperty("商品ID")
    private Long itemId;
    @ApiModelProperty("商品名称")
    private String name;
    @ApiModelProperty("商品图片")
    private String image;
    @ApiModelProperty("销量")
    private Integer sold;
    @ApiModelProperty("销售额（分）")
    private Long totalSales;
}