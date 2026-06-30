package com.hmall.trade.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@Accessors(chain = true)
@TableName("user_coupon")
public class UserCoupon implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.INPUT)
    private Long id;

    private Long userId;

    private Long couponId;

    /** 状态：1-未使用 2-已下单 3-已支付 4-已过期 */
    private Integer status;

    private Long orderId;

    private LocalDateTime receiveTime;

    /** 过期时间，NULL表示永久有效 */
    private LocalDateTime expireTime;

    private LocalDateTime useTime;
}
