package com.hmall.dashboard.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "仪表盘今日概览")
public class DashboardDTO {
    @ApiModelProperty("今日销售额（分）")
    private Long todaySales;
    @ApiModelProperty("今日订单数")
    private Long todayOrders;
    @ApiModelProperty("今日新增粉丝")
    private Long todayNewFans;
    @ApiModelProperty("待发货订单数")
    private Long pendingShip;
    @ApiModelProperty("秒杀转化率（%）")
    private Double seckillRate;
    @ApiModelProperty("商品总数")
    private Long totalItems;
    @ApiModelProperty("粉丝总数")
    private Long totalFans;
}
