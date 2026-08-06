package com.hmall.social.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * 商家发货地址 DTO（前端传输用，不含 shopId/userId，由后端从登录态填充）
 */
@Data
@ApiModel(description = "商家发货地址")
public class ShopAddressDTO {

    @ApiModelProperty("地址ID")
    private Long id;

    @ApiModelProperty("省")
    private String province;

    @ApiModelProperty("市")
    private String city;

    @ApiModelProperty("县/区")
    private String town;

    @ApiModelProperty("详细地址")
    private String street;

    @ApiModelProperty("联系人")
    private String contact;

    @ApiModelProperty("联系电话")
    private String mobile;

    @ApiModelProperty("是否当前发货地址 1是 0否")
    private Integer isDefault;

    @ApiModelProperty("备注")
    private String notes;
}
