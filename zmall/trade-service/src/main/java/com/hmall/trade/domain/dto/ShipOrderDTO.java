package com.hmall.trade.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * 商家发货请求 DTO
 * <p>不传任何字段时，默认走"模拟发货"流程（直接到货）。
 * <p>填写物流公司/单号时，将更新 order_logistics 记录。
 */
@Data
@ApiModel(description = "商家发货请求")
public class ShipOrderDTO {

    @ApiModelProperty("物流公司名称（如 顺丰速运 / 中通快递）")
    private String logisticsCompany;

    @ApiModelProperty("物流公司编码（如 SF / ZTO，便于API对接）")
    private String logisticsCompanyCode;

    @ApiModelProperty("物流单号")
    private String logisticsNumber;

    @ApiModelProperty("物流追踪链接（国际物流常用 URL 追踪）")
    private String trackingUrl;
}
