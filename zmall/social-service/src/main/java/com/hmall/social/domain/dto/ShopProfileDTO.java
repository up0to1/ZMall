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
}
