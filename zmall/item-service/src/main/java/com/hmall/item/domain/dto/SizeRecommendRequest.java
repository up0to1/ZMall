package com.hmall.item.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * 尺码推荐请求
 *
 * @author hmall
 * @since 2026-07-27
 */
@Data
@ApiModel(description = "尺码推荐请求")
public class SizeRecommendRequest {

    @NotNull(message = "身体信息不能为空")
    @ApiModelProperty("用户身体信息档案")
    private BodyProfileSimpleDTO bodyProfile;

    @NotBlank(message = "品类不能为空")
    @ApiModelProperty("品类：上衣/外套/下装/裤子/鞋/帽子")
    private String category;

    @ApiModelProperty("商品ID（可选，用于结合商品 SKU 实际尺码过滤）")
    private Long itemId;
}
