package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * AI 随心搭效果图入库请求（Python ai-outfit → Java item-service）
 *
 * <p>调用时机：用户在阶段二选 [满意-加购整套] 或 [满意-下单整套] 时，
 * Python ai-outfit 调用 Java 内部接口 POST /items/admin/outfit/records 入库。
 *
 * <p>设计文档 §3.3.1 ⑨A/⑨B + §3.3.4
 */
@ApiModel(description = "AI 随心搭效果图入库请求")
@Data
public class AiOutfitRecordCreateDTO {

    @ApiModelProperty(value = "关联 ai_task.task_id（阶段二 VTON 任务ID）", required = true)
    @NotBlank(message = "任务ID不能为空")
    private String taskId;

    @ApiModelProperty(value = "用户ID", required = true)
    @NotNull(message = "用户ID不能为空")
    private Long userId;

    @ApiModelProperty(value = "第几轮推荐（同一会话内多轮反馈时递增，默认1）")
    private Integer round;

    @ApiModelProperty(value = "Top3 中的索引 0/1/2", required = true)
    @NotNull(message = "套装索引不能为空")
    private Integer outfitIndex;

    /**
     * 套装详情 JSON 字符串
     * <p>结构：{items: [{itemId, itemName, shopId, shopName, category, price, imageUrl}], reason}
     * <p>Python 传入完整 JSON 字符串，Java 不解析（仅存储 + 透传给前端）
     */
    @ApiModelProperty(value = "套装详情 JSON 字符串", required = true)
    @NotBlank(message = "套装详情不能为空")
    private String outfitJson;

    @ApiModelProperty(value = "VTON 最终效果图 URL（一阶段直出 VTON 失败时为 null，前端展示'生成失败'）")
    private String vtonResultUrl;

    @ApiModelProperty(value = "用户原自拍照 OSS URL（v3.1 新增；model_image_source=photo 时非空，其余为 null）")
    private String userPhotoUrl;

    @ApiModelProperty(value = "模特图来源: photo（用户照片）/ system_pool（系统模特图）/ ai_generated（AI生成）")
    private String modelImageSource;

    @ApiModelProperty(value = "system_model_image.id（model_image_source=system_pool/ai_generated 时）")
    private Long modelImageId;

    @ApiModelProperty(value = "系统默认模特图 URL（用户选定的初始模特图，2026-08-06 新增；衣橱'模特/原始照片'展示用）")
    private String systemModelImageUrl;

    @ApiModelProperty(value = "满意动作: cart（加购）/ order（下单）/ pending（一阶段直出未采纳）", required = true)
    @NotBlank(message = "满意动作不能为空")
    private String acceptedAction;

    @ApiModelProperty(value = "本次 VTON 消耗的 credits 数（审计用）")
    private Integer creditsConsumed;

    @ApiModelProperty(value = "采纳状态：1=满意采纳（默认）/ 0=一阶段直出未采纳。为空时默认 1")
    private Integer accepted;
}
