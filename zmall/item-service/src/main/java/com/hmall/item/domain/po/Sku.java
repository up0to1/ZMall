package com.hmall.item.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * SKU表（库存量单元，具体规格商品）
 * 每个 SKU 对应一种规格组合（如 颜色=白色+尺码=M），有独立价格/库存/图片
 */
@Data
@TableName("sku")
public class Sku {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 关联的 SPU(item) id */
    private Long spuId;

    /** SKU编码（商家自定义，如 SP1001-WHITE-M） */
    private String skuCode;

    /** SKU名称（如 白色 M码） */
    private String name;

    /** 价格（分） */
    private Integer price;

    /** 库存数量 */
    private Integer stock;

    /** SKU图片（可覆盖SPU主图） */
    private String image;

    /** 销售属性键值对 JSON（如 {"颜色":"白色","尺码":"M"}） */
    private String specJson;

    /** 条形码 */
    private String barCode;

    /** 是否默认SKU：1=是（对应item.price/stock） 0=否 */
    private Integer isDefault;

    /** 状态：1=启用 0=禁用 */
    private Integer status;

    /** 排序 */
    private Integer sort;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
