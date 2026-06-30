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
    @ApiModelProperty("订单总金额（分）")
    private Integer totalFee;
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
    @ApiModelProperty("商品概要")
    private String itemName;
    @ApiModelProperty("商品总数量")
    private Integer itemCount;
    @ApiModelProperty("订单类型：1-商品订单 2-优惠券购买订单")
    private Integer orderType;
    @ApiModelProperty("订单明细列表")
    private List<OrderDetailVO> orderDetails;

    @Data
    public static class OrderDetailVO {
        @ApiModelProperty("商品ID")
        private Long itemId;
        @ApiModelProperty("商品名称")
        private String name;
        @ApiModelProperty("单价（分）")
        private Integer price;
        @ApiModelProperty("购买数量")
        private Integer num;
        @ApiModelProperty("商品图片")
        private String image;
        @ApiModelProperty("规格")
        private String spec;
    }
}
