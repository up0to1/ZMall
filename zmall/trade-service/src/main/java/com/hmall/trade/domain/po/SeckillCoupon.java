package com.hmall.trade.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@TableName("seckill_coupon")
public class SeckillCoupon implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "coupon_id", type = IdType.INPUT)
    private Long couponId;

    private Integer seckillStock;

    /** 已售库存（领取成功++，取消订单--） */
    private Integer soldStock;

    /** 开抢时间 */
    private LocalDateTime rushBeginTime;

    /** 抢购结束时间 */
    private LocalDateTime rushEndTime;

    private Integer maxPerUser;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
