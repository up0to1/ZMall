package com.hmall.item.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.math.BigDecimal;

/**
 * <p>
 * 尺码对照参考表
 * </p>
 *
 * <p>2026-07-27 新增：系统维护的统一尺码对照表。
 * <p>2026-07-27 改造：从"系统统一维护"改为"每店铺各自维护 + 系统模板（shop_id=0）"。
 * <ul>
 *   <li>shop_id = 0  → 系统预置模板（只读，商家可一键复制到自己店铺）</li>
 *   <li>shop_id > 0  → 商家自己维护的尺码表（商家后台 CRUD 管理）</li>
 * </ul>
 *
 * <p>商品与尺码表关联（方案C）：
 * <ul>
 *   <li>优先查 item.size_chart_id（商品专用绑定，针对偏码商品）</li>
 *   <li>回退到 shop_id + category + gender（店铺品类通用）</li>
 *   <li>最终回退到 shop_id=0（系统模板）</li>
 * </ul>
 *
 * <p>尺码推荐算法：多维加权匹配
 * <ul>
 *   <li>上衣/外套：胸围0.4 + 肩宽0.3 + 身高0.2 + 体重0.1</li>
 *   <li>下装/裤子：腰围0.5 + 臀围0.3 + 身高0.2</li>
 *   <li>鞋子：脚长0.9 + 脚宽0.1</li>
 *   <li>帽子：头围1.0（均码为主，头围超60cm提示加大款）</li>
 *   <li>配饰：无尺码需求（均码）</li>
 * </ul>
 *
 * @author hmall
 * @since 2026-07-27
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("size_chart_reference")
public class SizeChartReference implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /**
     * 店铺ID（0=系统模板只读，>0=商家自己维护）
     */
    private Long shopId;

    /**
     * 品类：上衣/外套/下装/鞋/帽子
     */
    private String category;

    /**
     * 性别：male/female/unisex
     */
    private String gender;

    /**
     * 尺码标签：S/M/L/XL/XXL 或 38/39/40/41
     */
    private String sizeLabel;

    /**
     * 身高下限(cm)
     */
    private Integer heightMin;

    /**
     * 身高上限(cm)
     */
    private Integer heightMax;

    /**
     * 体重下限(kg)
     */
    private BigDecimal weightMin;

    /**
     * 体重上限(kg)
     */
    private BigDecimal weightMax;

    /**
     * 胸围下限(cm)
     */
    private BigDecimal bustMin;

    /**
     * 胸围上限(cm)
     */
    private BigDecimal bustMax;

    /**
     * 腰围下限(cm)
     */
    private BigDecimal waistMin;

    /**
     * 腰围上限(cm)
     */
    private BigDecimal waistMax;

    /**
     * 臀围下限(cm)
     */
    private BigDecimal hipMin;

    /**
     * 臀围上限(cm)
     */
    private BigDecimal hipMax;

    /**
     * 脚长下限(cm)
     */
    private BigDecimal footLengthMin;

    /**
     * 脚长上限(cm)
     */
    private BigDecimal footLengthMax;

    /**
     * 肩宽下限(cm)
     */
    private BigDecimal shoulderWidthMin;

    /**
     * 肩宽上限(cm)
     */
    private BigDecimal shoulderWidthMax;

    /**
     * 头围下限(cm) —— 帽子品类用
     */
    private BigDecimal headCircumferenceMin;

    /**
     * 头围上限(cm) —— 帽子品类用
     */
    private BigDecimal headCircumferenceMax;

    /**
     * 描述（如"适合修身版型"）
     */
    private String description;

    /**
     * 排序（尺码从小到大）
     */
    private Integer sortOrder;
}
