package com.hmall.item.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * SPU属性值表（EAV-SPU普通属性存储）
 * 存储 SPU 的普通属性值（如 领型=圆领，面料=纯棉）
 * <p>value 字段：
 * <ul>
 *   <li>单选/多选属性：存 attribute_value.id 的 JSON（如 ["1","3"]）</li>
 *   <li>文本/数字属性：存实际值（如 "纯棉"）</li>
 * </ul>
 */
@Data
@TableName("spu_attr_value")
public class SpuAttrValue {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** 关联的 SPU(item) id */
    private Long spuId;

    /** 属性ID（如 1=颜色 2=尺码 3=材质 4=季节 5=风格） */
    private Long attributeId;

    /** 属性值（单选存attribute_value.id；多选存JSON数组；文本存实际值） */
    private String value;

    private LocalDateTime createTime;
}
