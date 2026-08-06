package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "商品实体")
public class ItemDTO {
    @ApiModelProperty("商品id")
    private Long id;
    @ApiModelProperty("SKU名称")
    private String name;
    @ApiModelProperty("价格（分）")
    private Integer price;
    @ApiModelProperty("成本价（分，用于利润统计，后台用，不向前台展示）")
    private Integer costPrice;
    @ApiModelProperty("库存数量")
    private Integer stock;
    @ApiModelProperty("商品图片")
    private String image;
    @ApiModelProperty("类目名称")
    private String category;
    @ApiModelProperty("品牌名称")
    private String brand;
    @ApiModelProperty("销量")
    private Integer sold;
    @ApiModelProperty("评论数")
    private Integer commentCount;
    @ApiModelProperty("是否是推广广告，true/false")
    private Boolean isAD;
    @ApiModelProperty("商品类别：1-普通商品 2-秒杀商品")
    private Integer itemType;
    @ApiModelProperty("商品状态 1-正常，2-下架，3-删除")
    private Integer status;
    @ApiModelProperty("商品详细描述，前台商品详情页展示")
    private String description;
    @ApiModelProperty("主图列表 JSON（如 [\"url1\",\"url2\",\"url3\"]，最多9张）")
    private String mainImages;
    @ApiModelProperty("详情图列表 JSON（如 [\"url1\",\"url2\",...]）")
    private String detailImages;
    @ApiModelProperty("适合性别：male/female/unisex")
    private String targetGender;
    @ApiModelProperty("养护说明（服装：30度以下机洗；茶叶：避光防潮；电子：避免进水）")
    private String careInstructions;
    @ApiModelProperty("产地（如 中国浙江/进口）")
    private String origin;
    @ApiModelProperty("重量（克，含包装）")
    private Integer weight;
    @ApiModelProperty("SPU编码（商品编码，商家自定义）")
    private String spuCode;
    @ApiModelProperty("类目ID（外键关联category.id）")
    private Long categoryId;
    @ApiModelProperty("创建人（商家ID）")
    private Long creater;

    // ===== EAV 属性传输字段（非数据库列，来自 spu_attr_value 表）=====
    @ApiModelProperty("颜色（EAV属性，如 红色）")
    private String color;
    @ApiModelProperty("季节（EAV属性，如 spring/summer/autumn/winter/all）")
    private String season;
    @ApiModelProperty("风格标签（EAV属性，JSON数组文本，如 [\"休闲\",\"通勤\"]）")
    private String styleTags;
    @ApiModelProperty("尺码（EAV属性，JSON数组文本，如 [\"S\",\"M\",\"L\"]）")
    private String sizes;
    @ApiModelProperty("材质（EAV属性，如 纯棉）")
    private String material;
}
