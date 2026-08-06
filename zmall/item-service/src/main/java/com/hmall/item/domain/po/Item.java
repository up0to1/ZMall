package com.hmall.item.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * <p>
 * 商品表
 * </p>
 *
 * @author 虎哥
 * @since 2023-05-05
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("item")
public class Item implements Serializable {

    private static final long serialVersionUID = 1L;

    /**
     * 商品id
     */
    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /**
     * SKU名称
     */
    private String name;

    /**
     * 价格（分）
     */
    private Integer price;

    /**
     * 成本价（分，用于利润统计）
     */
    private Integer costPrice;

    /**
     * 库存数量
     */
    private Integer stock;

    /**
     * 商品图片
     */
    private String image;

    /**
     * 类目名称
     */
    private String category;

    /**
     * 品牌名称
     */
    private String brand;

    /**
     * 销量
     */
    private Integer sold;

    /**
     * 评论数
     */
    private Integer commentCount;

    /**
     * 是否是推广广告，true/false
     */
    @TableField("isAD")
    private Boolean isAD;

    /**
     * 商品类别：1-普通商品 2-秒杀商品
     */
    private Integer itemType;

    /**
     * 商品状态 1-正常，2-下架
     * <p>注意：删除为物理删除（ItemServiceImpl.removeById），不再使用 status=3 软删除。
     * <p>商品被物理删除后，trade-service 的 order_detail 快照会被标记为
     * "【原商品名】商品已删除"，image 替换为 /uploads/items/deleted.jpg。
     */
    private Integer status;

    /**
     * 商品详细描述，前台商品详情页展示
     */
    private String description;

    /**
     * 主图列表 JSON（如 ["url1","url2","url3"]，最多9张，第一张为默认主图）
     */
    private String mainImages;

    /**
     * 详情图列表 JSON（如 ["url1","url2",...]，商品详情页轮播）
     */
    private String detailImages;

    /**
     * 适合性别：male/female/unisex
     */
    private String targetGender;

    /**
     * 养护说明（服装：30度以下机洗；茶叶：避光防潮；电子：避免进水）
     */
    private String careInstructions;

    /**
     * 产地（如 中国浙江/进口）
     */
    private String origin;

    /**
     * 重量（克，含包装）
     */
    private Integer weight;

    /**
     * SPU编码（商品编码，商家自定义）
     */
    private String spuCode;

    /**
     * 类目ID（外键关联category.id，用于继承属性模板attr_template_id）
     */
    private Long categoryId;

    /**
     * 创建时间
     */
    private LocalDateTime createTime;

    /**
     * 更新时间
     */
    private LocalDateTime updateTime;

    /**
     * 创建人
     */
    private Long creater;

    /**
     * 修改人
     */
    private Long updater;

    /**
     * 商品专用尺码表ID
     * <p>NULL=按店铺+品类自动匹配（默认行为）
     * <p>非NULL=针对偏码商品的专用绑定（方案C，覆盖店铺默认尺码表）
     * <p>2026-07-27 改造：放末尾便于向后兼容已有 INSERT 语句（item 表已有200条数据）
     */
    private Long sizeChartId;


}
