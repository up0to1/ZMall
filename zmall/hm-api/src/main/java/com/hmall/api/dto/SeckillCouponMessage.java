package com.hmall.api.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class SeckillCouponMessage {
    private Long couponId;
    private Long userId;
}
