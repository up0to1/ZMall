package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * SKU DTO（跨服务传输）
 * 用于 cart-service / trade-service 按 skuId 查询 SKU 信息（价格/图片/规格名）
 */
@Data
@ApiModel(description = "SKU 实体")
public class SkuDTO {
    @ApiModelProperty("SKU id")
    private Long id;
    @ApiModelProperty("关联的 SPU(item) id")
    private Long spuId;
    @ApiModelProperty("SKU编码")
    private String skuCode;
    @ApiModelProperty("SKU名称（如 白色 M码）")
    private String name;
    @ApiModelProperty("价格（分）")
    private Integer price;
    @ApiModelProperty("库存数量")
    private Integer stock;
    @ApiModelProperty("SKU图片")
    private String image;
    @ApiModelProperty("销售属性键值对 JSON（如 {\"颜色\":\"白色\",\"尺码\":\"M\"}）")
    private String specJson;
    @ApiModelProperty("是否默认SKU：1=是 0=否")
    private Integer isDefault;
    @ApiModelProperty("状态：1=启用 0=禁用")
    private Integer status;
}
