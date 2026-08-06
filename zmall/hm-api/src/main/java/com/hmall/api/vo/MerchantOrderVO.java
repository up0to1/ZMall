package com.hmall.api.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.util.List;

@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@ApiModel(description = "商家订单列表视图")
public class MerchantOrderVO {
    @ApiModelProperty("订单ID")
    private Long id;
    @ApiModelProperty("订单总金额（分，优惠后不含运费）")
    private Integer totalFee;
    @ApiModelProperty("运费（分，后台统计用，前台不展示）")
    private Integer postFee;
    @ApiModelProperty("支付类型")
    private Integer paymentType;
    @ApiModelProperty("用户ID")
    private Long userId;
    @ApiModelProperty("订单状态")
    private Integer status;
    @ApiModelProperty("状态文字")
    private String statusText;
    @ApiModelProperty("创建时间")
    private String createTime;
    @ApiModelProperty("支付时间")
    private String payTime;
    @ApiModelProperty("发货时间")
    private String consignTime;
    @ApiModelProperty("交易完成时间")
    private String endTime;
    @ApiModelProperty("交易关闭时间")
    private String closeTime;
    @ApiModelProperty("评价时间")
    private String commentTime;
    @ApiModelProperty("商品概要")
    private String itemName;
    @ApiModelProperty("商品总数量")
    private Integer itemCount;
    @ApiModelProperty("订单类型：1-商品订单 2-优惠券购买订单 3-秒杀商品订单")
    private Integer orderType;
    @ApiModelProperty("订单明细列表")
    private List<OrderDetailVO> orderDetails;
    @ApiModelProperty("物流信息（仅商家后台详情接口返回）")
    private LogisticsVO logistics;

    @Data
    public static class OrderDetailVO {
        @ApiModelProperty("商品ID")
        private Long itemId;
        @ApiModelProperty("SKU ID")
        private Long skuId;
        @ApiModelProperty("商品名称")
        private String name;
        @ApiModelProperty("售价（分）")
        private Integer price;
        @ApiModelProperty("成本价快照（分，后台统计用，前台不展示）")
        private Integer costPrice;
        @ApiModelProperty("购买数量")
        private Integer num;
        @ApiModelProperty("商品图片")
        private String image;
    }

    @Data
    public static class LogisticsVO {
        @ApiModelProperty("物流类型：1=国内快递 2=国际快递 3=专线物流 4=海外仓")
        private Integer logisticsType;
        @ApiModelProperty("物流单号")
        private String logisticsNumber;
        @ApiModelProperty("物流公司名称")
        private String logisticsCompany;
        @ApiModelProperty("物流追踪链接")
        private String trackingUrl;
        @ApiModelProperty("发货地文本（如 广东深圳）")
        private String shipFromText;
        @ApiModelProperty("收件人")
        private String contact;
        @ApiModelProperty("收件人手机号")
        private String mobile;
        @ApiModelProperty("省")
        private String province;
        @ApiModelProperty("市")
        private String city;
        @ApiModelProperty("区")
        private String town;
        @ApiModelProperty("街道")
        private String street;
        @ApiModelProperty("包裹重量（克）")
        private Integer weight;
        @ApiModelProperty("运费（分，商家承担，后台统计用，前台不展示）")
        private Integer shippingFee;
    }
}
