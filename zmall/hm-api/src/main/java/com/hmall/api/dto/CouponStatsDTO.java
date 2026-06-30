package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "优惠券统计")
public class CouponStatsDTO {

    @ApiModelProperty("发行总量")
    private Integer totalIssued;

    @ApiModelProperty("已领取总量")
    private Integer totalReceived;

    @ApiModelProperty("已使用总量")
    private Integer totalUsed;

    @ApiModelProperty("领取率")
    private double receiveRate;

    @ApiModelProperty("使用率")
    private double useRate;
}