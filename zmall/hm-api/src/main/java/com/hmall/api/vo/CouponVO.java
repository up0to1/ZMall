package com.hmall.api.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

@Data
@ApiModel(description = "优惠券视图")
public class CouponVO {

    @ApiModelProperty("优惠券ID")
    private Long id;

    @ApiModelProperty("名称")
    private String name;

    @ApiModelProperty("优惠方式：1-满减券 2-折扣券")
    private Integer type;

    @ApiModelProperty("优惠方式文字")
    private String typeText;

    @ApiModelProperty("券类别：1-普通券 2-秒杀券")
    private Integer couponType;

    @ApiModelProperty("券类别文字")
    private String couponTypeText;

    @ApiModelProperty("优惠值")
    private Integer discountValue;

    @ApiModelProperty("门槛金额")
    private Integer thresholdAmount;

    @ApiModelProperty("购买价格(分)")
    private Integer purchasePrice;

    @ApiModelProperty("购买价格文字")
    private String purchasePriceText;

    @ApiModelProperty("适用范围：1-全部商品 2-部分商品")
    private Integer scopeType;

    @ApiModelProperty("适用范围文字")
    private String scopeTypeText;

    @ApiModelProperty("适用商品ID列表")
    private List<Long> itemIds;

    @ApiModelProperty("领取后有效天数")
    private Integer validDays;

    @ApiModelProperty("有效期文字")
    private String validDaysText;

    @ApiModelProperty("发行总量")
    private Integer totalCount;

    @ApiModelProperty("已领取")
    private Integer receivedCount;

    @ApiModelProperty("已使用")
    private Integer usedCount;

    @ApiModelProperty("每人限领")
    private Integer perUserLimit;

    @ApiModelProperty("有效期开始时间")
    private String beginTime;

    @ApiModelProperty("有效期结束时间")
    private String endTime;

    @ApiModelProperty("状态")
    private Integer status;

    @ApiModelProperty("创建时间")
    private String createTime;

    // ========== 秒杀优惠券信息 ==========

    @ApiModelProperty("秒杀库存")
    private Integer seckillStock;

    @ApiModelProperty("秒杀每人限领")
    private Integer maxPerUser;

    @ApiModelProperty("秒杀开抢时间")
    private String rushBeginTime;

    @ApiModelProperty("秒杀结束时间")
    private String rushEndTime;
}
