package com.hmall.user.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * <p>
 * 用户身体信息档案
 * </p>
 *
 * <p>2026-07-27 新增：支持 AI 搭配时用户选中身体信息档案，用于尺码推荐。
 * 一个用户可有多条档案（不同时间记录身材变化），通过 is_default 标记默认档案。
 *
 * <p>字段按品类需求设计：
 * <ul>
 *   <li>上衣/外套：身高、体重、胸围、肩宽</li>
 *   <li>下装/裤子：身高、腰围、臀围</li>
 *   <li>鞋子：脚长、脚宽</li>
 *   <li>帽子：头围（可选，均码为主）</li>
 *   <li>配饰：无身体字段需求（均码）</li>
 * </ul>
 *
 * @author hmall
 * @since 2026-07-27
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("user_body_profile")
public class BodyProfile implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /**
     * 用户ID
     */
    private Long userId;

    /**
     * 档案名称（如"2026年7月身材"）
     */
    private String profileName;

    /**
     * 性别：male/female
     */
    private String gender;

    /**
     * 身高(cm) 140-210
     */
    private Integer height;

    /**
     * 体重(kg) 35-150
     */
    private BigDecimal weight;

    /**
     * 肩宽(cm) 35-55
     */
    private BigDecimal shoulderWidth;

    /**
     * 胸围(cm) 70-130
     */
    private BigDecimal bust;

    /**
     * 腰围(cm) 50-130
     */
    private BigDecimal waist;

    /**
     * 臀围(cm) 70-140
     */
    private BigDecimal hip;

    /**
     * 脚长(cm) 20-32
     */
    private BigDecimal footLength;

    /**
     * 脚宽(cm) 8-12
     */
    private BigDecimal footWidth;

    /**
     * 头围(cm) 50-65
     */
    private BigDecimal headCircumference;

    /**
     * 年龄段：18-25/26-35/36-45/46+
     */
    private String ageRange;

    /**
     * 体型：slim/standard/curvy/plus
     */
    private String bodyType;

    /**
     * 是否默认档案：1=默认 0=普通
     */
    private Integer isDefault;

    /**
     * 是否有效：1有效 0已删除
     */
    private Integer isActive;

    /**
     * 测量日期
     */
    private LocalDate measuredAt;

    /**
     * 创建时间
     */
    private LocalDateTime createTime;

    /**
     * 更新时间
     */
    private LocalDateTime updateTime;
}
