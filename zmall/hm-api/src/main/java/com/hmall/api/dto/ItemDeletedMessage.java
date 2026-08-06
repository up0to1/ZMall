package com.hmall.api.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 商品被物理删除时，item-service 发送给 trade-service 的内部消息体
 * <p>用于标记所有引用该商品的 order_detail 快照（name 加 "【原商品名】商品已删除" 前缀，
 * image 改为占位图），使商品删除后订单仍能正常显示。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ItemDeletedMessage {
    /** 被删除的商品ID */
    private Long itemId;
    /** 被删除的商品名称（用于快照前缀，可为 null） */
    private String itemName;
}
