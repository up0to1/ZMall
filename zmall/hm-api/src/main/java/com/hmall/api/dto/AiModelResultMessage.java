package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

/**
 * AI 模特图结果回流消息（Python ai-models → Java item-service）
 *
 * <p>投递到 ai.model.exchange → ai.model.result 队列。
 *
 * <p>2026-07-19 v2 重构：取消三级池后，不再需要 modelImageToSave / modelImageToSaveUrl
 * （上传即入池由 Java 侧在上传接口完成，Python 不再回传模特图保存信息）。
 *
 * <p>2026-07-20 死字段清理：删除 type/userId 字段（Python 发送但 Java 从不读取）。
 * type 字段冗余（listener 只处理 AI_MODEL 一种类型），userId 字段可从 ai_task 表获取。
 *
 * <p>2026-07-22 v4 多 Agent 决策字段对齐：新增 overallScore / styleFeatures /
 * styleFeaturesDivergence / postProcessedImageUrl 四个字段。
 * 注意：Python 侧 extra 中的 starRating 是多 Agent 评估的星级（0-5），
 * 与 ai_task.star_rating（商家评分 1-5）语义不同，故不在此消息体中传递——
 * 多 Agent 评估星级只走 WebSocket/Redis 给前端实时展示，不落 ai_task 表。
 * agentEvaluations（5 角色评估详情）仅 Python 内部日志用，也不传递。
 *
 * <p>2026-07-26 v5 多图模式扩展：
 * <ul>
 *   <li>多换装模式（multi_outfit）：新增 sceneResults / outfitCombinations /
 *       combinationReasons，每个场景的独立结果（含 result_urls/overall_score/
 *       star_rating/agent_evaluations 等）</li>
 *   <li>多姿势模式（multi_pose）：新增 poseResults，每个姿势的独立结果</li>
 *   <li>agentEvaluations（5 角色评估详情）：从 v4 内部日志字段升级为持久化字段，
 *       多图模式下取第 1 个成功场景/姿势的评估作为代表，存入 ai_task.agent_evaluations</li>
 * </ul>
 */
@ApiModel(description = "AI 模特图结果回流 MQ 消息")
@Data
public class AiModelResultMessage {

    @ApiModelProperty("任务ID")
    private String taskId;

    @ApiModelProperty("店铺 shopId")
    private Long shopId;

    @ApiModelProperty("状态: SUCCESS / FAILED")
    private String status;

    @ApiModelProperty("结果图 URL 列表（N 张中间图 + 1 张最终图，按链式顺序）")
    private List<String> resultUrls;

    @ApiModelProperty("各图对应的品类（前端标注用，如 [\"上衣\",\"下装\",\"帽子\"]）")
    private List<String> itemCategories;

    @ApiModelProperty("商家选定的商品 ID 列表（发布时校验用）")
    private List<Long> itemIds;

    @ApiModelProperty("错误信息（失败时）")
    private String errorMsg;

    // ===== v4 多 Agent 决策字段（2026-07-22 新增）=====
    // 仅 enableMultiAgent=1 时有值，链式 VTON 路径这些字段为 null

    @ApiModelProperty("多 Agent 综合评分（0.0-1.0，导演 Supervisor 汇总 5 角色评估后给出）")
    private Double overallScore;

    @ApiModelProperty("风格特征 JSON（策划阶段 5 角色 Agent 输出的风格描述聚合）")
    private String styleFeatures;

    @ApiModelProperty("风格分歧度（5 角色 Agent 输出差异程度，字符串形式）")
    private String styleFeaturesDivergence;

    @ApiModelProperty("后处理后图 URL（图生图 API 接入后才有值，当前为 null）")
    private String postProcessedImageUrl;

    // ===== v5 多图模式字段（2026-07-26 新增）=====

    @ApiModelProperty("v5 多 Agent 评估详情 JSON（5 角色评估，内部日志+监控看板用，多图模式取首场景代表）")
    private String agentEvaluations;

    @ApiModelProperty("v5 生成模式：single / multi_outfit / multi_pose（回传用于校验与持久化路由）")
    private String generationMode;

    @ApiModelProperty("v5 多换装组合（仅 multi_outfit 模式，每套是 itemId 列表）")
    private List<List<Long>> outfitCombinations;

    @ApiModelProperty("v5 多换装组合推荐理由（与 outfitCombinations 等长）")
    private List<String> combinationReasons;

    @ApiModelProperty("v5 多换装场景结果 JSON（仅 multi_outfit 模式，每个场景的独立结果）")
    private String sceneResults;

    @ApiModelProperty("v5 多姿势结果 JSON（仅 multi_pose 模式，每个姿势的独立结果）")
    private String poseResults;
}
