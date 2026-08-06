package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.time.LocalDateTime;
import java.util.List;

/**
 * AI 任务记录 DTO（对应 ai_task 表）
 */
@ApiModel(description = "AI 任务记录")
@Data
public class AiTaskDTO {

    @ApiModelProperty("主键ID")
    private Long id;

    @ApiModelProperty("任务ID（UUID）")
    private String taskId;

    @ApiModelProperty("用户ID")
    private Long userId;

    @ApiModelProperty("店铺ID（AI模特任务才有）")
    private Long shopId;

    @ApiModelProperty("商品ID（AI模特任务才有，单商品场景保留；多商品场景用 itemIds）")
    private Long itemId;

    @ApiModelProperty("任务类型: OUTFIT_PRODUCT / OUTFIT_AGENT / MODEL / OUTFIT_CANDIDATE(v3阶段一) / OUTFIT_VTON(v3阶段二)")
    private String taskType;

    @ApiModelProperty("状态: PENDING/PROCESSING/SUCCESS/FAILED/TIMEOUT")
    private String status;

    @ApiModelProperty("v3 阶段标识: candidate / vton / null（旧版任务）")
    private String phase;

    @ApiModelProperty("结果图 URL 列表（多商品链式 VTON：N 张中间图 + 1 张最终图）")
    private List<String> resultUrls;

    @ApiModelProperty("搭配商品 ID 列表")
    private List<Long> outfitItems;

    @ApiModelProperty("商家选定的商品 ID 列表（AI 模特多商品场景，发布时校验用）")
    private List<Long> itemIds;

    @ApiModelProperty("各图对应的品类（AI 模特前端标注用，如 [\"上衣\",\"下装\",\"帽子\"]）")
    private List<String> itemCategories;

    @ApiModelProperty("错误信息")
    private String errorMsg;

    /** v3 评分字段（2026-07-20 新增） */
    @ApiModelProperty("商家五星评分（1-5，NULL 表示未评分）")
    private Integer starRating;

    @ApiModelProperty("评分标签数组（如 [\"质感好\",\"比例协调\"]）")
    private List<String> ratingTags;

    @ApiModelProperty("评分备注")
    private String ratingNote;

    @ApiModelProperty("拒绝原因（商家不满意时填写）")
    private String rejectReason;

    @ApiModelProperty("已发布到商品主图的 itemId（NULL 表示未发布）")
    private Long publishedItemId;

    @ApiModelProperty("最终图是否已入系统模特图池（0=否, 1=是）")
    private Integer savedToPool;

    /** v4 多 Agent 决策字段（2026-07-22 新增） */
    @ApiModelProperty("是否启用多 Agent 决策（0=否, 1=是）")
    private Integer enableMultiAgent;

    @ApiModelProperty("多 Agent 综合评分（0.0-1.0，AI 评估客观分数，与 starRating 语义不同）")
    private Double overallScore;

    @ApiModelProperty("风格特征 JSON（5 角色 Agent 策划阶段输出）")
    private String styleFeatures;

    @ApiModelProperty("风格分歧度（5 角色 Agent 输出差异程度）")
    private String styleFeaturesDivergence;

    @ApiModelProperty("后处理后图 URL（图生图 API 接入后才有值，当前为 null）")
    private String postProcessedImageUrl;

    /** v5 多换装模式字段（2026-07-26 新增） */
    @ApiModelProperty("v5 多 Agent 评估详情 JSON（5 角色评估，内部日志用）")
    private String agentEvaluations;

    @ApiModelProperty("v5 生成模式：single（单图，默认）/ multi_outfit（多换装）")
    private String generationMode;

    @ApiModelProperty("v5 多换装组合（仅 multi_outfit 模式，每套是 itemId 列表）")
    private List<List<Long>> outfitCombinations;

    @ApiModelProperty("v5 多换装组合推荐理由（与 outfitCombinations 等长）")
    private List<String> combinationReasons;

    @ApiModelProperty("v5 多换装场景结果（仅 multi_outfit 模式，每个场景的独立结果）")
    private String sceneResults;

    @ApiModelProperty("v5 多姿势结果（仅 multi_pose 模式，每个姿势的独立结果）")
    private String poseResults;

    @ApiModelProperty("创建时间")
    private LocalDateTime createdAt;

    @ApiModelProperty("完成时间")
    private LocalDateTime finishedAt;

    @ApiModelProperty("排队位置（PENDING 状态时表示前面还有几个任务，null 表示无需排队或非排队状态）")
    private Integer queuePosition;
}
