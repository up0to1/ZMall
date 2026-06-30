package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "订单统计")
public class OrderStatsDTO {
    @ApiModelProperty("今日新订单数")
    private Long todayNew;
    @ApiModelProperty("待发货订单数")
    private Long pendingShip;
    @ApiModelProperty("已发货订单数")
    private Long shipped;
    @ApiModelProperty("退款中订单数")
    private Long refunding;
    @ApiModelProperty("今日销售额（分）")
    private Long todaySales;
}