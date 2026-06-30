package com.hmall.trade.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@ApiModel(description = "秒杀结果")
public class SeckillResult {

    @ApiModelProperty("结果码：0-成功，1-库存不足，2-重复下单，3-活动未开始，4-活动已结束")
    private Integer code;

    @ApiModelProperty("订单ID，成功时返回")
    private Long orderId;

    public static SeckillResult success(Long orderId) {
        return new SeckillResult(0, orderId);
    }

    public static SeckillResult stockNotEnough() {
        return new SeckillResult(1, null);
    }

    public static SeckillResult repeatOrder() {
        return new SeckillResult(2, null);
    }

    public static SeckillResult notStarted() {
        return new SeckillResult(3, null);
    }

    public static SeckillResult ended() {
        return new SeckillResult(4, null);
    }
}
