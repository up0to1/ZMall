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
 * AI 模特任务反馈表（v3 新增，2026-07-20）
 *
 * <p>记录商家对 AI 模特生成结果的评分与拒绝原因，用于：
 * <ol>
 *   <li>≥3★ + 商家同意 → 最终图自动入 system_model_image 池（source=1）</li>
 *   <li>≥4★ + 发布到商品主图 → 奖励 1 credit（每日上限 5 次）</li>
 *   <li>拒绝原因 ≥20 字 → 奖励 1 credit（每日上限 3 次）</li>
 *   <li>数据分析：统计 AI 生成质量、商家满意度、常见拒绝原因</li>
 * </ol>
 *
 * <p>唯一索引 uk_task_id_type(task_id, feedback_type)：同一任务同类型反馈仅允许一次
 *（一个任务只能评分一次 + 只能拒绝一次，但评分后可以再拒绝，反之亦然）。
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("ai_model_image_feedback")
public class AiModelImageFeedback implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 关联的 AI 任务ID */
    private String taskId;

    /** 提交反馈的商家userId */
    private Long userId;

    /** 店铺ID（等于商家userId） */
    private Long shopId;

    /** 反馈类型: RATING(评分) / REJECT(拒绝) */
    private String feedbackType;

    /** 五星评分（1-5，feedback_type=RATING 时必填） */
    private Integer starRating;

    /** 评分标签数组 JSON（如 ["质感好","比例协调"]） */
    private String ratingTags;

    /** 评分备注 */
    private String ratingNote;

    /** 拒绝原因（feedback_type=REJECT 时必填，≥20 字可奖励 credit） */
    private String rejectReason;

    /** 评分对应的最终效果图URL（入池时用） */
    private String resultUrl;

    /** 任务对应的商品ID列表 JSON（入池时记录搭配商品） */
    private String itemIds;

    /** 本次反馈已奖励的 credits 数（0=未奖励） */
    private Integer awardedCredits;

    /** 是否已入系统模特图池（0=否, 1=是） */
    private Integer savedToPool;

    @TableField("created_at")
    private LocalDateTime createdAt;
}
