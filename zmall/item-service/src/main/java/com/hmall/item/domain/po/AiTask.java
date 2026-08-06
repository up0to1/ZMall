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
 * AI 任务记录表
 *
 * 对应数据库 ai_task 表，记录 AI 模特图 / AI 随心搭任务全生命周期。
 * 由 Java 侧写入（PENDING），Python 侧更新进度（PROCESSING/SUCCESS/FAILED），
 * Java 侧通过 MQ 消费 Python 回流消息更新终态。
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("ai_task")
public class AiTask implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 任务ID（UUID） */
    private String taskId;

    /** 用户ID */
    private Long userId;

    /** 店铺ID（AI 模特任务才有） */
    private Long shopId;

    /** 商品ID（AI 模特任务才有） */
    private Long itemId;

    /** 任务类型: OUTFIT_PRODUCT / OUTFIT_AGENT / MODEL / OUTFIT_CANDIDATE(v3阶段一) / OUTFIT_VTON(v3阶段二) */
    private String taskType;

    /** 状态: PENDING/PROCESSING/SUCCESS/FAILED/TIMEOUT */
    private String status;

    /**
     * v3 阶段标识: candidate / vton / null（旧版任务）
     * <p>用于 v3 两阶段交互：阶段一 candidate 完成后置 SUCCESS，
     * 用户选定套装后创建新的 vton 任务（taskType=OUTFIT_VTON, phase=vton）。
     */
    private String phase;

    /**
     * 输入参数 JSON
     * AI 模特（旧版单商品）：{ itemId, ossUrl, modelParams, sceneType }
     * AI 模特（新版多商品链式 VTON，2026-07-19）：{ itemIds, modelImageSource, modelImageId, uploadedModelUrl, saveToShopPool }
     * AI 随心搭：{ itemIds, prompt, photoSessionKey }
     * AI 随心搭 v3 阶段一：{ styleTags, sceneDesc, color, categories, shopId, note, photoSessionKey, useDefaultModel }
     * AI 随心搭 v3 阶段二：{ candidateTaskId, selectedCandidateIndexes, vtonRetryCount }
     */
    private String inputParams;

    /** 结果图 URL 列表 JSON（多商品链式 VTON：N 张中间图 + 1 张最终图） */
    private String resultUrls;

    /** 搭配商品 ID 列表 JSON */
    private String outfitItems;

    /**
     * 商家选定的商品 ID 列表 JSON（AI 模特多商品场景，2026-07-19 新增）
     *
     * <p>发布时校验用：商家选定的 itemId 必须在此列表内，防止跨店铺发布。
     */
    private String itemIds;

    /**
     * 各图对应的品类列表 JSON（AI 模特多商品场景，2026-07-19 新增）
     *
     * <p>前端标注用：如 ["上衣","下装","帽子"]，让商家知道每张中间图对应哪件商品。
     */
    private String itemCategories;

    /** 耗时毫秒 */
    private Integer costMs;

    /** 错误信息 */
    private String errorMsg;

    /**
     * 商家五星评分（1-5，NULL 表示未评分）
     * <p>v3 新增（2026-07-20）：商家在 AI 模特生成结果页对最终图评分。
     * ≥3★ + 商家同意 → 最终图自动入 system_model_image 池（source=1）
     * ≥4★ + 发布到商品主图 → 奖励 1 credit（每日上限 5 次）
     */
    private Integer starRating;

    /** 评分标签数组 JSON（如 ["质感好","比例协调"]） */
    private String ratingTags;

    /** 评分备注 */
    private String ratingNote;

    /**
     * 拒绝原因（商家不满意时填写）
     * <p>≥20 字可奖励 1 credit（每日上限 3 次）
     */
    private String rejectReason;

    /**
     * 已发布到商品主图的 itemId（NULL 表示未发布）
     * <p>商家在评分后选 [一键发布] 时写入，用于防重发布 + 统计发布转化率
     */
    private Long publishedItemId;

    /**
     * 最终图是否已入系统模特图池（0=否, 1=是）
     * <p>≥3★ + 商家同意时自动入池，置 1 防止重复入池
     */
    private Integer savedToPool;

    /**
     * 是否启用多 Agent 决策（0=否, 1=是）
     * <p>v4 新增（2026-07-22）：启用后走 5 角色 Agent + 导演 Supervisor 的 LangGraph 工作流，
     * 否走链式 VTON。Java 创建任务时写入，Python 消费时据此切换流程。
     */
    private Integer enableMultiAgent;

    /**
     * 多 Agent 综合评分（0.0-1.0，导演 Supervisor 汇总 5 角色评估后给出）
     * <p>v4 新增（2026-07-22）：与 starRating（商家评分）语义不同，此字段为 AI 评估的客观分数。
     * 仅 enableMultiAgent=1 时有值。
     */
    private Double overallScore;

    /**
     * 风格特征 JSON（策划阶段 5 角色 Agent 输出的风格描述聚合）
     * <p>v4 新增（2026-07-22）：如 {"eu_style":"...","asia_style":"...","lighting":"..."}
     * 仅 enableMultiAgent=1 时有值。
     */
    private String styleFeatures;

    /**
     * 风格分歧度（5 角色 Agent 输出差异程度，字符串形式）
     * <p>v4 新增（2026-07-22）：用于评估多 Agent 决策一致性，分歧大时可能需要人工介入。
     * 仅 enableMultiAgent=1 时有值。
     */
    private String styleFeaturesDivergence;

    /**
     * 后处理后图 URL（多 Agent 决策后处理节点输出）
     * <p>v4 新增（2026-07-22）：当导演决策需要后处理（补光/调色/换妆面）时，
     * 后处理节点对 VTON 输出图做二次精修后的结果图 URL。
     * 当前后处理节点为降级实现（TODO 接入图生图 API），此字段暂为 null。
     */
    private String postProcessedImageUrl;

    /**
     * v5 多 Agent 评估详情 JSON
     * <p>v4 设计但 v5 落地：5 角色 Agent 评估详情（stylistEu/stylistAsia/lighting/makeup/photographer）。
     * 多换装模式下取第 1 个成功场景的评估作为代表。
     * 内部日志 + 监控看板用，不直接展示给商家。
     */
    private String agentEvaluations;

    /**
     * v5 新增（2026-07-26）：生成模式
     * <p>"single"（默认）：单图模式（一件下装+一件上装 / 一件全身套装）
     * <p>"multi_outfit"：多换装模式（多套组合并行 VTON，支持 2 件下装+1 件上装等搭配）
     * <p>多换装模式：同脸/同妆造 + 不同服装 + 不同姿势
     */
    private String generationMode;

    /**
     * v5 新增（2026-07-26）：多换装组合 JSON
     * <p>外层 list 每个元素代表一套搭配组合，内层 list 是该套的 itemId 列表。
     * <p>示例：[[101,201],[101,202]] 表示 2 套组合。
     * <p>仅 generationMode=multi_outfit 时有值。
     */
    private String outfitCombinations;

    /**
     * v5 新增（2026-07-26）：多换装组合推荐理由 JSON
     * <p>与 outfitCombinations 等长，每套组合的推荐理由（颜色/风格/场景说明）。
     */
    private String combinationReasons;

    /**
     * v5 新增（2026-07-26）：多换装场景结果 JSON
     * <p>每个场景的独立结果（含 scene_idx/combination/result_urls/overall_score/star_rating/
     * agent_evaluations/post_processed_image_url/decision_reason_cn 等）。
     * <p>仅 generationMode=multi_outfit 时有值，单图模式为 null。
     */
    private String sceneResults;

    /**
     * v5 新增（2026-07-26）：多姿势结果 JSON
     * <p>每个姿势的独立结果（含 pose_idx/pose_name/pose_prompt/result_urls/overall_score/
     * star_rating/agent_evaluations/post_processed_image_url/decision_reason_cn 等）。
     * <p>仅 generationMode=multi_pose 时有值。
     */
    private String poseResults;

    @TableField("created_at")
    private LocalDateTime createdAt;

    @TableField("finished_at")
    private LocalDateTime finishedAt;
}
