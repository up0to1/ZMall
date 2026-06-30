package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

@Data
@ApiModel(description = "秒杀商品设置")
public class SeckillItemDTO {
    @ApiModelProperty("商品ID")
    private Long itemId;
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

    /**
     * 批量创建秒杀商品时的请求体
     */
    @Data
    @ApiModel(description = "批量设置秒杀商品请求")
    public static class BatchCreateRequest {
        @ApiModelProperty("商品ID列表")
        private List<Long> itemIds;
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
    }
}