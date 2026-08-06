package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

/**
 * AI 模特图生成任务下发消息（Java item-service → Python ai-models）
 *
 * <p>投递到 ai.model.exchange → ai.model.generate 队列。
 *
 * <p>2026-07-19 v2 重构：取消三级模特图池，统一为系统模特图池。
 *
 * <p>Python 消费侧（ai-models/app/mq/model_consumer.py）期望字段：camelCase 命名，
 * Jackson2JsonMessageConverter 默认输出 camelCase，两端字段名一致。
 *
 * <p>消息体设计（v2 简化）：
 * <ul>
 *   <li>items 按 VTON 链式顺序排好（全身套装→上衣→下装→帽子），Python 不重新排序</li>
 *   <li>modelImageUrl 是 Java 侧从系统模特图池解析后的最终 URL，Python 不查 DB</li>
 *   <li>itemIds 用于结果回流时校验发布权限</li>
 *   <li>取消 uploadedModelInfo / saveToShopPool：上传即入池由 Java 侧在上传接口完成</li>
 *   <li>v4 新增 enableMultiAgent（2026-07-22）：控制 Python 走多 Agent 工作流还是链式 VTON</li>
 *   <li>v5 新增 generationMode/outfitCombinations（2026-07-26）：支持多换装模式</li>
 * </ul>
 */
@ApiModel(description = "AI 模特图生成任务 MQ 消息（多商品链式 VTON v2 + v4 多 Agent + v5 多换装）")
@Data
public class AiModelGenerateMessage {

    @ApiModelProperty("任务ID（UUID）")
    private String taskId;

    @ApiModelProperty("商家 userId（用于 WebSocket 推送）")
    private Long userId;

    @ApiModelProperty("店铺 shopId（用于配额维度）")
    private Long shopId;

    @ApiModelProperty("商品列表（按 VTON 链式顺序排好：全身套装→上衣→下装→帽子）")
    private List<ItemInfo> items;

    @ApiModelProperty("商家选定的商品 ID 列表（发布时校验用）")
    private List<Long> itemIds;

    @ApiModelProperty("模特图 URL（Java 侧已从系统模特图池解析好）")
    private String modelImageUrl;

    /**
     * v4 新增（2026-07-22）：是否启用多 Agent 决策
     * <p>true=走 5 角色 Agent + 导演 Supervisor 的 LangGraph 工作流（ai-models 内部执行）
     * <p>false=走链式 VTON（默认，无 LLM 决策）
     * <p>Python 消费侧（model_consumer._process_task）据此切换流程分支。
     * <p>注：v5 多换装模式下此字段被忽略（generationMode 优先级更高）
     */
    @ApiModelProperty("是否启用多 Agent 决策（默认 false，走链式 VTON）")
    private Boolean enableMultiAgent;

    /**
     * v5 新增（2026-07-26）：生成模式
     * <p>"single"（默认）：单图模式（一件下装+一件上装 / 一件全身套装，链式 VTON 或多 Agent）
     * <p>"multi_outfit"：多换装模式（多套组合并行 VTON，支持 2 件下装+1 件上装等搭配）
     * <p>"multi_pose"：多姿势模式（1 次 VTON + N 次 O1 图生图生成姿势变体，同服装不同姿势）
     * <p>Python 消费侧据此路由到 multi_outfit_graph / multi_pose_graph 工作流。
     * <p>multi_outfit：同脸/同妆造 + 不同服装 + 不同姿势（每套独立 VTON 自然产生不同姿势）
     * <p>multi_pose：同脸/同妆造 + 同服装 + 不同姿势（O1 图生图基于 VTON 基准图生成姿势变体）
     */
    @ApiModelProperty("生成模式：single（单图，默认）/ multi_outfit（多换装）/ multi_pose（多姿势）")
    private String generationMode;

    /**
     * v5 新增（2026-07-26）：多换装组合（仅 generationMode=multi_outfit 时有效）
     * <p>外层 list 每个元素代表一套搭配组合，内层 list 是该套的 itemId 列表。
     * <p>示例：[[101,201],[101,202]] 表示 2 套组合，第 1 套用商品 101+201，第 2 套用 101+202。
     * <p>可为空：为空时 Python 侧自动调用 LLM 推荐组合。
     */
    @ApiModelProperty("多换装组合（仅 multi_outfit 模式，每套是 itemId 列表，可空由 Python LLM 生成）")
    private List<List<Long>> outfitCombinations;

    /**
     * v5 新增（2026-07-26）：多换装组合推荐理由（与 outfitCombinations 等长）
     * <p>当 Java 侧预生成组合（调用 Python /api/v1/model/outfit-combinations）时回填。
     */
    @ApiModelProperty("多换装组合推荐理由（与 outfitCombinations 等长，可选）")
    private List<String> combinationReasons;

    /**
     * v5 新增（2026-07-26）：姿势数量（仅 generationMode=multi_pose 时有效）
     * <p>默认 3，最大 4。Python 侧会调用 LLM 推荐对应数量的姿势 prompt。
     * <p>每个姿势基于 VTON 基准图通过 O1 图生图生成变体。
     */
    @ApiModelProperty("姿势数量（仅 multi_pose 模式，默认 3，最大 4）")
    private Integer poseCount;

    /**
     * 商品信息（Python 消费侧用）
     * <p>v5 扩展：新增 name/color/styleTags 字段，供多换装 LLM 搭配推荐使用。
     * 旧字段（itemId/ossUrl/category）保持兼容。
     */
    @Data
    @ApiModel(description = "商品信息（MQ 消息内嵌）")
    public static class ItemInfo {
        @ApiModelProperty("商品ID")
        private Long itemId;

        @ApiModelProperty("商品白底图 OSS URL")
        private String ossUrl;

        @ApiModelProperty("品类（中文，如 上衣/下装/全身套装/帽子）")
        private String category;

        @ApiModelProperty("商品名称（v5 多换装 LLM 搭配推荐用）")
        private String name;

        @ApiModelProperty("主色（v5 多换装 LLM 搭配推荐用）")
        private String color;

        @ApiModelProperty("风格标签（v5 多换装 LLM 搭配推荐用）")
        private List<String> styleTags;

        public ItemInfo() {
        }

        public ItemInfo(Long itemId, String ossUrl, String category) {
            this.itemId = itemId;
            this.ossUrl = ossUrl;
            this.category = category;
        }

        public ItemInfo(Long itemId, String ossUrl, String category, String name, String color, List<String> styleTags) {
            this.itemId = itemId;
            this.ossUrl = ossUrl;
            this.category = category;
            this.name = name;
            this.color = color;
            this.styleTags = styleTags;
        }
    }
}
