package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotEmpty;
import javax.validation.constraints.NotNull;
import javax.validation.constraints.Size;
import java.util.List;

/**
 * AI 模特图生成请求（商家端）
 *
 * <p>2026-07-19 v2 重构：取消三级模特图池，统一为系统模特图池。
 *
 * <p>设计文档 §1.2 请求流（v2）：
 * <ul>
 *   <li>商家从自己店铺选 1-4 件商品（必须穿搭类目：上衣/下装/全身套装/帽子）</li>
 *   <li>商家从系统模特图池选一张模特图（GET /system-images 拉列表，POST /system-images 上传新图）</li>
 *   <li>Java 校验品类冲突规则（同品类最多 1 件 + 全身套装与上衣/下装互斥）</li>
 *   <li>Java 校验 modelImageId 存在 + is_active=1 → 解析 modelImageUrl</li>
 *   <li>Java 排好链式顺序后发 MQ</li>
 * </ul>
 *
 * <p>允许的 9 种合法组合（single 模式）：
 * [上衣]、[下装]、[全身套装]、[帽子]、[上衣+下装]、[上衣+帽子]、[下装+帽子]、
 * [上衣+下装+帽子]、[全身套装+帽子]
 *
 * <p>v5 多图模式（2026-07-26 新增）：
 * <ul>
 *   <li>generationMode="single"（默认）：单图模式，限制 1 件下装+1 件上装</li>
 *   <li>generationMode="multi_outfit"：多换装模式，可放宽到 2 件下装+1 件上装（多套搭配）</li>
 *   <li>generationMode="multi_pose"：多姿势模式，同服装不同姿势（商品规则同 single）</li>
 * </ul>
 */
@ApiModel(description = "AI 模特图生成请求（多商品链式 VTON，使用系统模特图池）")
@Data
public class AiModelGenerateDTO {

    @ApiModelProperty(value = "商品 ID 列表（1-4 件，必须归属当前商家）", required = true)
    @NotEmpty(message = "商品ID列表不能为空")
    @Size(min = 1, max = 4, message = "商品数量必须在1-4件之间")
    private List<Long> itemIds;

    @ApiModelProperty(value = "系统模特图 ID（必填，从 /system-images 接口选取）", required = true)
    @NotNull(message = "模特图ID不能为空")
    private Long modelImageId;

    /**
     * v5 新增（2026-07-26）：生成模式
     * <p>"single"（默认）：单图模式
     * <p>"multi_outfit"：多换装模式（多套搭配并行 VTON）
     * <p>"multi_pose"：多姿势模式（同服装不同姿势，O1 图生图生成 N 个姿势变体）
     * <p>不同模式的商品品类校验规则不同，详见 OutfitCategories.validateAiModelCategoryCombo
     */
    @ApiModelProperty("v5 生成模式：single（单图，默认）/ multi_outfit（多换装）/ multi_pose（多姿势）")
    private String generationMode;

    /**
     * v5 新增（2026-07-26）：多换装组合（仅 multi_outfit 模式）
     * <p>外层 list 每个元素代表一套搭配组合，内层 list 是该套的 itemId 列表。
     * <p>可为空：为空时由 Python 侧 LLM 推荐组合（推荐流程：商家先调
     * POST /api/v1/model/outfit-combinations 预览组合，确认后回填）。
     */
    @ApiModelProperty("v5 多换装组合（仅 multi_outfit 模式，每套是 itemId 列表，可空由 Python LLM 生成）")
    private List<List<Long>> outfitCombinations;

    /**
     * v5 新增（2026-07-26）：姿势数量（仅 multi_pose 模式）
     * <p>默认 3，最大 4。Python 侧会调用 LLM 推荐对应数量的姿势 prompt。
     */
    @ApiModelProperty("v5 姿势数量（仅 multi_pose 模式，默认 3，最大 4）")
    private Integer poseCount;
}
