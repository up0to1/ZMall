package com.hmall.api.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "秒杀商品视图（含预热状态）")
public class SeckillItemVO {

    @ApiModelProperty("商品ID")
    private Long itemId;

    @ApiModelProperty("商品名称")
    private String itemName;

    @ApiModelProperty("商品图片")
    private String image;

    @ApiModelProperty("商品原价（分）")
    private Integer price;

    @ApiModelProperty("商品类别：1-普通商品 2-秒杀商品")
    private Integer itemType;

    @ApiModelProperty("秒杀库存")
    private Integer seckillStock;

    @ApiModelProperty("秒杀价格（分）")
    private Integer seckillPrice;

    @ApiModelProperty("每人限购数量")
    private Integer maxPerUser;

    @ApiModelProperty("开抢时间")
    private String rushBeginTime;

    @ApiModelProperty("抢购结束时间")
    private String rushEndTime;

    @ApiModelProperty("预热状态：0-未预热, 1-已预热")
    private Integer preheatStatus;

    @ApiModelProperty("Redis当前剩余库存")
    private Integer redisStock;
}
