package com.hmall.item.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

@Data
@TableName("category")
public class Category {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String name;

    private Long parentId;

    /** 层级：1-一级类目 2-二级类目 3-三级类目 */
    private Integer level;

    /** 关联的属性模板ID（用于继承属性模板） */
    private Long attrTemplateId;

    private Integer sort;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
