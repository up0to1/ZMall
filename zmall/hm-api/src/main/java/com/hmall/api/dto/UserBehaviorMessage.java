package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 用户行为事件消息（Phase 2.5 个性化推荐画像数据源）
 *
 * <p>消息流向：Java 微服务（item/cart/trade）→ user.behavior.exchange → Python ai-outfit UserBehaviorConsumer
 * <br>消费方：Python UserBehaviorMqConsumer → text-embedding-v4 文本编码 → Qdrant zmall_user_behavior collection
 *
 * <p>4 类行为事件（type 字段）：
 * <ul>
 *   <li>ITEM_VIEW：用户浏览商品详情页（item-service 埋点）</li>
 *   <li>CART_ADD：用户加购（cart-service 埋点）</li>
 *   <li>ORDER_PLACE：用户下单（trade-service 埋点）</li>
 *   <li>OUTFIT_ACCEPT：用户采纳 AI 搭配（Python ai-outfit accept 接口埋点）</li>
 * </ul>
 *
 * <p>Routing Key 规则：user.behavior.{type}（如 user.behavior.ITEM_VIEW）
 * <br>Python 消费侧用通配符 user.behavior.* 绑定，一个队列消费所有类型。
 *
 * <p>字段命名：camelCase（Jackson2JsonMessageConverter 默认输出，与 Python 侧 payload 字段名对齐）
 */
@ApiModel(description = "用户行为事件消息（Phase 2.5 个性化推荐画像）")
@Data
public class UserBehaviorMessage {

    @ApiModelProperty("用户 ID")
    private Long userId;

    @ApiModelProperty("商品 ID")
    private Long itemId;

    @ApiModelProperty("店铺 ID")
    private Long shopId;

    @ApiModelProperty("商品品类（中文，如上衣/下装/鞋等）")
    private String category;

    @ApiModelProperty("商品名称（纯文本向量检索的核心文本）")
    private String name;

    @ApiModelProperty("商品颜色（英文，如 black/white/red）")
    private String color;

    @ApiModelProperty("适用季节 spring/summer/autumn/winter/all（EAV属性）")
    private String season;

    @ApiModelProperty("商品价格（元）")
    private Double price;

    @ApiModelProperty("行为类型：ITEM_VIEW / CART_ADD / ORDER_PLACE / OUTFIT_ACCEPT")
    private String type;

    @ApiModelProperty("事件时间戳（ISO 格式，如 2026-07-28T10:00:00）")
    private String timestamp;

    @ApiModelProperty("商品图片 URL（保留兼容，纯文本向量模式下不用于编码）")
    private String imageUrl;

    @ApiModelProperty("风格标签列表（从商品 EAV 属性提取）")
    private List<String> styleTags;

    @ApiModelProperty("商品性别：male/female/unisex（性别对齐检查用）")
    private String itemGender;

    @ApiModelProperty("用户性别：male/female（性别对齐检查用）")
    private String userGender;

    public UserBehaviorMessage() {
    }

    public UserBehaviorMessage(Long userId, Long itemId, Long shopId, String category, String name,
                                String color, String season, Double price, String type, String timestamp,
                                String imageUrl, List<String> styleTags,
                                String itemGender, String userGender) {
        this.userId = userId;
        this.itemId = itemId;
        this.shopId = shopId;
        this.category = category;
        this.name = name;
        this.color = color;
        this.season = season;
        this.price = price;
        this.type = type;
        this.timestamp = timestamp;
        this.imageUrl = imageUrl;
        this.styleTags = styleTags;
        this.itemGender = itemGender;
        this.userGender = userGender;
    }
}
