package com.hmall.item.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 系统模特图 PO（全平台共用的统一模特图池）
 *
 * <p>2026-07-19 重构：取消三级池（platform/shop/upload），合并为统一的系统模特图池。
 *
 * <p>核心规则：
 * <ul>
 *   <li>所有商家上传的模特图都进入同一个池子</li>
 *   <li>所有商家都能查询 is_active=1 的模特图</li>
 *   <li>仅创建者（uploader_user_id）能修改/删除自己的模特图</li>
 *   <li>AI 模特功能 + AI 随心搭（用户无自拍照时）共用此池</li>
 * </ul>
 *
 * <p>图片来源（source 字段）：
 * <ul>
 *   <li>0：商家直接上传（POST /system-images multipart）</li>
 *   <li>1：AI 模特任务后保存（商家临时上传时勾选"保存到系统池"）</li>
 *   <li>2：平台运营上传（后台管理，预留）</li>
 *   <li>3：AI 自动生成（AI 随心搭兜底生成，预留）</li>
 * </ul>
 *
 * <p>图片存储：优先 OSS，OSS 未启用则本地存储（{@code zmall-nginx/html/uploads/model-images/}）。
 * 数据库 image_url 字段存相对路径（本地模式，如 {@code /uploads/model-images/xxx.jpg}）
 * 或完整 URL（OSS 模式）。
 *
 * <p>对应数据库 system_model_image 表。
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("system_model_image")
public class SystemModelImage implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 模特图 URL（相对路径或完整 URL） */
    private String imageUrl;

    /** 上传者用户ID（权限校验：仅创建者可修改/删除） */
    private Long uploaderUserId;

    /** 性别: male/female */
    private String gender;

    /** 肤色: fair/wheat/dark */
    private String skinTone;

    /** 身高（cm），150-200 */
    private Integer height;

    /** 体重（kg），35-120 */
    private Integer weight;

    /** 年龄段: 18-25 / 26-35 / 36-45 / 46+ */
    private String ageRange;

    /** 体型: slim/standard/curvy/plus */
    private String bodyType;

    /** 风格标签 JSON（如 ["通勤","休闲","欧美"]） */
    private String styleTags;

    /** 备注（≤50字） */
    private String note;

    /** 是否系统推荐默认图：1=是 0=否（is_default=1 的优先返回给前端） */
    private Integer isDefault;

    /** 来源: 0=商家上传 1=AI模特任务后保存 2=平台运营 3=AI自动生成 */
    private Integer source;

    /** 是否启用（软删标记）：1=启用 0=下架 */
    private Integer isActive;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;
}
