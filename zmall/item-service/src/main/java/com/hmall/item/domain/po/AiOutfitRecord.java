package com.hmall.item.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * AI 随心搭效果图入库记录（v3 新增，v3.2 分层保存 2026-07-28）
 *
 * <p>v3.2 修订：从"仅保存满意套装"改为"分层保存"：
 * <ul>
 *   <li>accepted=1：用户满意（加购/下单/保存到衣橱），永久保留</li>
 *   <li>accepted=0：用户不满意（反馈调整/换一套），保留 90 天用于画像负样本</li>
 *   <li>accepted=2：用户未操作（24h 定时任务标记），保留 30 天用于统计</li>
 * </ul>
 *
 * <p>写入时机：
 * <ul>
 *   <li>用户点 [保存到衣橱/加购/下单] → accepted=1（Python ai-outfit 调 Java 入库）</li>
 *   <li>用户点 [反馈调整/换一套] → accepted=0（Python ai-outfit 调 Java 入库 + 记录 feedback_summary）</li>
 *   <li>定时任务扫描 24h 未操作 task → accepted=2（Java 定时任务入库）</li>
 * </ul>
 *
 * <p>查询时机：用户"我的搭配历史"页面查看；AI 个性化推荐优化（Phase 2.5）；商家端 AI 看板统计。
 *
 * <p>设计文档 §3.3.4 + §3.16 历史记录策略
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("ai_outfit_record")
public class AiOutfitRecord implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 关联 ai_task.task_id（阶段二 VTON 任务ID） */
    private String taskId;

    /** 用户ID */
    private Long userId;

    /** 第几轮推荐（同一会话内多轮反馈时递增） */
    private Integer round;

    /** Top3 中的索引 0/1/2 */
    private Integer outfitIndex;

    /**
     * 套装详情 JSON（v3.2 完整结构）
     * <p>结构：{items: [{itemId, itemName, shopId, shopName, category, price, imageUrl, color, size, isMain, isWardrobePicked, stockStatus}], reason, score, sizeMap, context: {targetGender, photoMode, styleTags, sceneDesc, color, categories, shopIds, budgetMax, season, round, modelProfile}, feedbackHistory: [{round, action, reason}], vtonMeta: {modelImageSource, modelImageId, userPhotoUrl, creditsConsumed}}
     * <p>Python 传入完整 JSON 字符串，Java 不解析（仅存储 + 透传给前端）
     */
    private String outfitJson;

    /** VTON 最终效果图 URL */
    private String vtonResultUrl;

    /**
     * 用户原自拍照 OSS URL（v3.1 新增）
     * <p>accept 时持久化：用户上传照片时同步上传 OSS，URL 存 Redis，accept 时读出传给 Java
     * <p>model_image_source=photo 时非空；system_pool/ai_generated 时为 NULL
     * <p>用于"我的衣橱"页面展示用户原自拍照（item_type=4 → user_wardrobe.original_photo_url）
     */
    private String userPhotoUrl;

    /**
     * 模特图来源: photo（用户照片）/ system_pool（系统模特图）/ ai_generated（AI生成）
     */
    private String modelImageSource;

    /** system_model_image.id（model_image_source=system_pool/ai_generated 时） */
    private Long modelImageId;

    /**
     * 系统默认模特图 URL（2026-08-06 新增）
     * <p>用户选定系统模特时前端传 systemModelImageUrl（即初始模特图），
     * 衣橱"模特/原始照片"展示用；真人照片模式为 NULL
     */
    private String systemModelImageUrl;

    /**
     * 关联订单ID（已下单状态时非空；订单取消/超时后清空，2026-08-06 新增）
     * <p>由 trade-service 下单成功回调 mark-ordered 写入；取消/超时回调 revert-ordered 清空。
     * 搭配历史页据此展示"已下单"标签（acceptedAction=order + orderId 非空）。
     */
    private Long orderId;

    /** 下单前 accepted 快照（订单取消/超时回退用，2026-08-06 新增） */
    private Integer prevAccepted;

    /** 下单前 accepted_action 快照（订单取消/超时回退用，2026-08-06 新增） */
    private String prevAcceptedAction;

    /**
     * 用户操作状态（v3.2 修订）
     * <p>1=满意（加购/下单/保存到衣橱）
     * <p>0=不满意（反馈调整/换一套）
     * <p>2=未操作（24h 定时任务标记）
     */
    private Integer accepted;

    /**
     * 满意动作: cart（加购）/ order（下单）/ saved（保存到衣橱，v3.2 新增）
     */
    private String acceptedAction;

    /**
     * 操作类型细分（v3.2 新增）
     * <p>replace_single / uncoordinated / item_dislike / regenerate / style_mismatch / random / closed
     * <p>用于画像分析和商家看板统计
     */
    private String acceptedType;

    /**
     * 反馈摘要（v3.2 新增）
     * <p>accepted=0 时记录用户反馈内容摘要，用于画像负样本
     * <p>长度限制 500 字符
     */
    private String feedbackSummary;

    /**
     * 搭配上下文 JSON（v3.2 新增）
     * <p>记录生成搭配时的上下文（性别/风格/场景/模特档案等），便于离线分析
     * <p>与 outfitJson.context 字段内容相同，单独存储便于 SQL 查询
     */
    private String contextJson;

    /**
     * 父任务 ID（v3.2 新增）
     * <p>系统模特模式转自拍照模式 re-vton 时关联原任务
     * <p>普通推荐时为 NULL
     */
    private String parentTaskId;

    /** 本次 VTON 消耗的 credits 数（审计用） */
    private Integer creditsConsumed;

    @TableField("created_at")
    private LocalDateTime createdAt;

    @TableField("updated_at")
    private LocalDateTime updatedAt;
}
