package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

@Data
@ApiModel(description = "秒杀优惠券预热设置")
public class SeckillCouponDTO {
    @ApiModelProperty("优惠券ID")
    private Long couponId;
    @ApiModelProperty("秒杀库存")
    private Integer seckillStock;
    @ApiModelProperty("每人限领数量（已废弃，秒杀优惠券固定限领1张）")
    private Integer maxPerUser;
    @ApiModelProperty("开抢时间")
    private String rushBeginTime;
    @ApiModelProperty("抢购结束时间")
    private String rushEndTime;

    /**
     * 批量创建秒杀优惠券时的请求体
     */
    @Data
    @ApiModel(description = "批量设置秒杀优惠券请求")
    public static class BatchCreateRequest {
        @ApiModelProperty("优惠券ID列表")
        private List<Long> couponIds;
        @ApiModelProperty("秒杀库存")
        private Integer seckillStock;
        @ApiModelProperty("每人限领数量")
        private Integer maxPerUser;
        @ApiModelProperty("开抢时间")
        private String rushBeginTime;
        @ApiModelProperty("抢购结束时间")
        private String rushEndTime;
    }
}
