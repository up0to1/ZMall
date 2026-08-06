package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * 利润趋势 DTO（按天）
 */
@Data
@ApiModel(description = "利润趋势")
public class ProfitTrendDTO {

    @ApiModelProperty("日期（yyyy-MM-dd）")
    private String date;

    @ApiModelProperty("销售额（分）")
    private Long sales;

    @ApiModelProperty("商品成本（分）")
    private Long cost;

    @ApiModelProperty("运费（分）")
    private Long shippingFee;

    @ApiModelProperty("净利润（分）")
    private Long netProfit;
}
