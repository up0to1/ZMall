package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * 利润统计 DTO
 */
@Data
@ApiModel(description = "利润统计")
public class ProfitStatsDTO {

    @ApiModelProperty("统计订单数（已完成：状态4/6）")
    private Integer orderCount;

    @ApiModelProperty("销售额（单位：分，订单 totalFee 之和）")
    private Long totalSales;

    @ApiModelProperty("商品成本（单位：分，order_detail.cost_price * num 之和）")
    private Long totalCost;

    @ApiModelProperty("运费成本（单位：分，order_logistics.shipping_fee 之和）")
    private Long totalShippingFee;

    @ApiModelProperty("优惠折扣（单位：分，order.discount_amount 之和）")
    private Long totalDiscount;

    @ApiModelProperty("毛利润（单位：分，= 销售额 - 商品成本）")
    private Long grossProfit;

    @ApiModelProperty("净利润（单位：分，= 销售额 - 商品成本 - 运费）")
    private Long netProfit;

    @ApiModelProperty("利润率（百分比，= 净利润 / 销售额 * 100）")
    private Double profitMargin;
}
