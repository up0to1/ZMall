package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

@Data
@ApiModel(description = "优惠券DTO")
public class CouponDTO {

    @ApiModelProperty("优惠券ID")
    private Long id;

    @ApiModelProperty("优惠券名称")
    private String name;

    @ApiModelProperty("优惠方式：1-满减券 2-折扣券")
    private Integer type;

    @ApiModelProperty("券类别：1-普通券 2-秒杀券")
    private Integer couponType;

    @ApiModelProperty("优惠值")
    private Integer discountValue;

    @ApiModelProperty("使用门槛金额(分)")
    private Integer thresholdAmount;

    @ApiModelProperty("购买价格(分)，0表示免费领取")
    private Integer purchasePrice;

    @ApiModelProperty("适用范围：1-全部商品 2-部分商品")
    private Integer scopeType;

    @ApiModelProperty("适用商品ID列表，scope_type=2时必填")
    private List<Long> itemIds;

    @ApiModelProperty("领取后有效天数，NULL表示永久有效，0表示当天有效")
    private Integer validDays;

    @ApiModelProperty("发行总量")
    private Integer totalCount;

    @ApiModelProperty("每人限领")
    private Integer perUserLimit;

    @ApiModelProperty("有效期开始时间")
    private String beginTime;

    @ApiModelProperty("有效期结束时间")
    private String endTime;

    @ApiModelProperty("状态：1-上架 0-下架")
    private Integer status;

    // ========== 秒杀优惠券额外字段 ==========

    @ApiModelProperty("秒杀库存（couponType=2时必填）")
    private Integer seckillStock;

    @ApiModelProperty("秒杀每人限领（couponType=2时必填）")
    private Integer maxPerUser;

    @ApiModelProperty("秒杀开抢时间（couponType=2时必填）")
    private String rushBeginTime;

    @ApiModelProperty("秒杀结束时间（couponType=2时必填）")
    private String rushEndTime;
}
