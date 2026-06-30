package com.hmall.trade.domain.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class SeckillOrderMessage {
    private Long orderId;
    private Long userId;
    private Long itemId;
    private Long couponId;
}
