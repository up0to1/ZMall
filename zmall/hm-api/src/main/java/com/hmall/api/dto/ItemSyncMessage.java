package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

/**
 * 商品库同步消息（Java item-service → Python ai-outfit 消费）
 *
 * <p>用于将商品上下架/增删改事件同步到 Qdrant 向量库，支持 AI 随心搭：
 * <ul>
 *   <li>US-AT-13 按颜色筛选（color 字段）</li>
 *   <li>US-AT-18 季节感知过滤（season 字段）</li>
 *   <li>US-AT-20 商品上下架同步 Qdrant（isActive 字段）</li>
 *   <li>P1 优化：stock 字段 + Qdrant payload 存库存，节点2 filter stock>0</li>
 *   <li>P1 优化：fieldsChanged 字段，消费侧仅图片变更时才重新 encode（省 API 调用）</li>
 *   <li>性别过滤扩展（2026-07-27）：targetGender 字段，节点2 filter target_gender IN (user_gender, "unisex")，避免跨性别推荐</li>
 * </ul>
 *
 * <p>Python 消费侧（item_sync_consumer.py）期望字段：camelCase 命名，
 * Jackson2JsonMessageConverter 默认输出 camelCase，两端字段名一致。
 *
 * <p>routing key:
 * <ul>
 *   <li>{@code item.upsert} - 新增/更新/上下架（isActive=true 写入，isActive=false 软删除）</li>
 *   <li>{@code item.delete} - 物理删除（仅需 itemId）</li>
 * </ul>
 *
 * <p>穿搭类目过滤（P0）：仅上衣/下装/全身套装/鞋/帽子/包/配饰 7 个类目才会发 MQ 同步,
 * 其他类目（手机/拉拉裤等）不发，避免污染 Qdrant。
 * "全身套装"=成套衣服/连衣裙/连体衣/旗袍等成套衣物；半身裙归"下装"。
 * 详见 {@link com.hmall.api.constant.OutfitCategories}。
 */
@ApiModel(description = "商品库同步消息")
@Data
public class ItemSyncMessage {

    @ApiModelProperty("商品ID")
    private Long itemId;

    @ApiModelProperty("店铺ID（暂未实现店铺管理，默认 0 表示平台商品）")
    private Long shopId;

    @ApiModelProperty("商品名称（纯文本向量检索的核心文本，含丰富描述）")
    private String name;

    @ApiModelProperty("类目名称（中文，如 上衣/下装/全身套装/鞋）")
    private String category;

    @ApiModelProperty("主色（中文，如 红色/黑色）")
    private String color;

    @ApiModelProperty("适用季节 spring/summer/autumn/winter/all")
    private String season;

    @ApiModelProperty("价格（分）")
    private Integer price;

    @ApiModelProperty("是否上架有效（true=上架同步，false=下架软删除）")
    private Boolean isActive;

    @ApiModelProperty("商品图片 URL")
    private String imageUrl;

    @ApiModelProperty("风格标签列表（暂未实现，默认空数组）")
    private List<String> styleTags;

    @ApiModelProperty("库存数量（P1 优化：Qdrant payload 存库存，节点2 filter stock>0）")
    private Integer stock;

    @ApiModelProperty("本次变更的字段列表（P1 优化：如 [image,price,stock]，消费侧仅 image 变更时才重新 encode）")
    private List<String> fieldsChanged;

    @ApiModelProperty("适合性别 male/female/unisex（性别过滤扩展 2026-07-27：节点2 据此过滤 Qdrant，避免跨性别推荐）")
    private String targetGender;

    public ItemSyncMessage() {
    }

    public ItemSyncMessage(Long itemId, Long shopId, String name, String category, String color, String season,
                           Integer price, Boolean isActive, String imageUrl, List<String> styleTags,
                           Integer stock, List<String> fieldsChanged, String targetGender) {
        this.itemId = itemId;
        this.shopId = shopId;
        this.name = name;
        this.category = category;
        this.color = color;
        this.season = season;
        this.price = price;
        this.isActive = isActive;
        this.imageUrl = imageUrl;
        this.styleTags = styleTags;
        this.stock = stock;
        this.fieldsChanged = fieldsChanged;
        this.targetGender = targetGender;
    }
}
