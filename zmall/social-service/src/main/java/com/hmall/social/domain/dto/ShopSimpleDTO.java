package com.hmall.social.domain.dto;

import lombok.Data;

@Data
public class ShopSimpleDTO {
    private Long id;
    private String shopName;
    /** 店铺所属用户ID（商家 userId，用于按店铺搜索单品时对应 item.creater） */
    private Long userId;
}
