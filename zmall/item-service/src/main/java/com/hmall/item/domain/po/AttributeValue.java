package com.hmall.item.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

/**
 * 属性可选值表（EAV-属性值字典）
 * 单选/多选属性的可选值，如"颜色"→[白色,黑色,红色]
 */
@Data
@TableName("attribute_value")
public class AttributeValue {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 关联的属性ID */
    private Long attributeId;

    /** 属性值（如 白色/V领） */
    private String value;

    /** 排序 */
    private Integer sort;
}
