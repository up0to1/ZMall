package com.hmall.user.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * <p>
 * 我的衣橱
 * </p>
 *
 * @author hmall
 * @since 2026-07-18
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("user_wardrobe")
public class Wardrobe implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /**
     * 用户ID
     */
    private Long userId;

    /**
     * 条目类型：1=单品模式 2=自定义上传 3=全身自拍 4=AI搭配效果图（v3.1 新增，accept 自动入库）
     */
    private Integer itemType;

    /**
     * 商品ID（item_type=1 时关联商品，可空）
     */
    private Long itemId;

    /**
     * 图片URL（item_type=2/3 时 OSS URL，可空）
     */
    private String photoUrl;

    /**
     * AI 穿搭效果图 URL（item_type=4 时非空，来自 ai_outfit_record.vton_result_url；v3.1 新增）
     */
    private String outfitResultUrl;

    /**
     * 用户原自拍照 URL（item_type=4 + model_image_source=photo 时非空；用系统模特图时为 null；v3.1 新增）
     */
    private String originalPhotoUrl;

    /**
     * AI 搭配单品详情 JSON：{items:[...], reason}（item_type=4 时非空；v3.1 新增）
     */
    private String outfitJson;

    /**
     * 关联 ai_outfit_record.id（item_type=4 时非空，跨服务关联；v3.1 新增）
     */
    private Long recordId;

    /**
     * 中文品类（可空）
     */
    private String category;

    /**
     * 中文颜色（可空）
     */
    private String color;

    /**
     * 风格标签 JSON 数组字符串，如 ["通勤","简约"]（可空）
     */
    private String styleTags;

    /**
     * 场景标注（可空）
     */
    private String sceneDesc;

    /**
     * 是否有效：1有效 0已删除
     */
    private Integer isActive;

    /**
     * 创建时间
     */
    private LocalDateTime createTime;

    /**
     * 更新时间
     */
    private LocalDateTime updateTime;
}
