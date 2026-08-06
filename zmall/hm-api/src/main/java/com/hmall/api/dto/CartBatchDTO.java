package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotEmpty;
import java.util.List;

/**
 * 套装批量加购请求
 *
 * AI 随心搭推荐出 N 件搭配商品后，前端一次性把多件商品加入购物车。
 */
@ApiModel(description = "套装批量加购请求")
@Data
public class CartBatchDTO {

    @ApiModelProperty(value = "商品ID列表（按搭配顺序）", required = true)
    @NotEmpty(message = "加购商品列表不能为空")
    private List<Long> itemIds;

    @ApiModelProperty("套装标识（可选，用于看板统计套装加购转化率）")
    private String bundleId;
}
