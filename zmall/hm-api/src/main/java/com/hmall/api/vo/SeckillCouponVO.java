package com.hmall.api.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "秒杀优惠券视图（含预热状态）")
public class SeckillCouponVO {

    @ApiModelProperty("优惠券ID")
    private Long couponId;

    @ApiModelProperty("优惠券名称")
    private String couponName;

    @ApiModelProperty("优惠方式：1-满减券 2-折扣券")
    private Integer type;

    @ApiModelProperty("优惠值")
    private Integer discountValue;

    @ApiModelProperty("购买价格(分)")
    private Integer purchasePrice;

    @ApiModelProperty("秒杀库存")
    private Integer seckillStock;

    @ApiModelProperty("每人限领数量")
    private Integer maxPerUser;

    @ApiModelProperty("开抢时间")
    private String rushBeginTime;

    @ApiModelProperty("抢购结束时间")
    private String rushEndTime;

    @ApiModelProperty("预热状态：0-未预热, 1-已预热")
    private Integer preheatStatus;

    @ApiModelProperty("Redis当前剩余库存")
    private Integer redisStock;
}