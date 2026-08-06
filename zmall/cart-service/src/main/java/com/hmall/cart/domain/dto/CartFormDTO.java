package com.hmall.cart.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "新增购物车商品表单实体")
public class CartFormDTO {
    @ApiModelProperty("商品id")
    private Long itemId;
    @ApiModelProperty("SKU ID（多SKU商品的具体规格组合；不传则后端按默认SKU处理）")
    private Long skuId;
    @ApiModelProperty("商品标题")
    private String name;
    @ApiModelProperty("价格,单位：分")
    private Integer price;
    @ApiModelProperty("商品图片")
    private String image;

    /**
     * 套装标识（P1-11修复：套装批量加购时透传，用于写入 cart.bundle_id）
     * 为空表示普通加购。BeanUtils.copyBean 会按同名属性拷贝到 Cart。
     */
    @ApiModelProperty("套装标识（套装加购时透传，可选）")
    private String bundleId;
}
