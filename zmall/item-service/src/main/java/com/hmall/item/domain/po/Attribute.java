package com.hmall.item.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 属性定义表（EAV-属性元数据）
 * 区分销售属性（is_sale_attr=1，如颜色/尺码）和普通属性（is_sale_attr=0，如材质/季节/风格）
 */
@Data
@TableName("attribute")
public class Attribute {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 属性名称（如 颜色/尺码/材质/季节/风格） */
    private String name;

    /** 输入类型：1-单选 2-多选 3-文本 4-数字 */
    private Integer inputType;

    /** 单位（如 厘米/克，可为空） */
    private String unit;

    /** 是否销售属性：1-是 0-否（销售属性参与SKU规格组合） */
    private Integer isSaleAttr;

    /** 是否必填：1-是 0-否 */
    private Integer isRequired;

    /** 是否可搜索：1-是 0-否（用于前端筛选） */
    private Integer isSearchable;

    /** 排序 */
    private Integer sort;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
