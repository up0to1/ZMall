package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;
import lombok.experimental.Accessors;

@ApiModel(description = "订单明细条目")
@Data
@Accessors(chain = true)
public class OrderDetailDTO {
    @ApiModelProperty("商品id")
    private Long itemId;
    @ApiModelProperty("SKU ID（多SKU商品的具体规格组合；不传则后端按默认SKU处理）")
    private Long skuId;
    @ApiModelProperty("商品购买数量")
    private Integer num;
}
