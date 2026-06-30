package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "预热状态响应")
public class PreheatStatusDTO {

    @ApiModelProperty("商品ID")
    private Long itemId;

    @ApiModelProperty("DB中秒杀库存")
    private Integer dbStock;

    @ApiModelProperty("Redis当前库存")
    private Integer redisStock;

    @ApiModelProperty("是否已预热")
    private Boolean preheated;
}