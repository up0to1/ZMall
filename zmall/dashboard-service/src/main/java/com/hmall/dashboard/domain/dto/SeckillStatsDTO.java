package com.hmall.dashboard.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "秒杀活动数据")
public class SeckillStatsDTO {
    @ApiModelProperty("秒杀商品ID")
    private Long itemId;
    @ApiModelProperty("商品名称")
    private String itemName;
    @ApiModelProperty("总库存")
    private Integer totalStock;
    @ApiModelProperty("已售数量")
    private Integer soldCount;
    @ApiModelProperty("售罄率（%）")
    private Double sellOutRate;
}
