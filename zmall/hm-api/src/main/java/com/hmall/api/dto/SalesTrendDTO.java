package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "销售趋势")
public class SalesTrendDTO {
    @ApiModelProperty("日期")
    private String date;
    @ApiModelProperty("当日销售额（分）")
    private Long sales;
    @ApiModelProperty("当日订单数")
    private Long orders;
}