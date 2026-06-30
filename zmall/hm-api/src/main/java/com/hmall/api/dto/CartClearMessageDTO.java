package com.hmall.api.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Set;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class CartClearMessageDTO {
    private Long orderId;
    private Long userId;
    private Set<Long> itemIds;
}