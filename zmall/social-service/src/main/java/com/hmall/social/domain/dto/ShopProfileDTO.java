package com.hmall.social.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "商家信息")
public class ShopProfileDTO {
    @ApiModelProperty("店铺ID")
    private Long id;
    @ApiModelProperty("商家用户ID")
    private Long userId;
    @ApiModelProperty("店铺名称")
    private String shopName;
    @ApiModelProperty("店铺Logo")
    private String logo;
    @ApiModelProperty("店铺简介")
    private String description;
    @ApiModelProperty("联系电话")
    private String contactPhone;
    @ApiModelProperty("店铺地址")
    private String address;

    @ApiModelProperty("当前发货地（如 广东深圳，来自 shop_address 表 is_default=1 的记录）")
    private String currentShipFrom;

    @ApiModelProperty("钱包余额（单位：分，由前端调用 /credits/balance 接口填充）")
    private Integer walletBalance;

    @ApiModelProperty("Credits 余额（由前端调用 /credits/balance 接口填充）")
    private Integer creditsBalance;
}
