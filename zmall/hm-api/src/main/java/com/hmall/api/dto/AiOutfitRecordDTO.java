package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * AI 随心搭效果图记录 DTO（对应 ai_outfit_record 表）
 *
 * <p>用于"我的搭配历史"页面展示。
 * outfitJson 字段保留原始 JSON 字符串，前端自行解析展示单品列表。
 */
@ApiModel(description = "AI 随心搭效果图记录")
@Data
public class AiOutfitRecordDTO {

    @ApiModelProperty("主键ID")
    private Long id;

    @ApiModelProperty("关联 ai_task.task_id（阶段二 VTON 任务ID）")
    private String taskId;

    @ApiModelProperty("用户ID")
    private Long userId;

    @ApiModelProperty("第几轮推荐")
    private Integer round;

    @ApiModelProperty("Top3 中的索引 0/1/2")
    private Integer outfitIndex;

    @ApiModelProperty("套装详情 JSON 字符串：{items: [...], reason}")
    private String outfitJson;

    @ApiModelProperty("VTON 最终效果图 URL")
    private String vtonResultUrl;

    @ApiModelProperty("用户原自拍照 OSS URL（v3.1 新增；model_image_source=photo 时非空，其余为 null）")
    private String userPhotoUrl;

    @ApiModelProperty("模特图来源: photo / system_pool / ai_generated")
    private String modelImageSource;

    @ApiModelProperty("system_model_image.id")
    private Long modelImageId;

    @ApiModelProperty("系统默认模特图 URL（用户选定的初始模特图，2026-08-06 新增；衣橱'模特/原始照片'展示用）")
    private String systemModelImageUrl;

    @ApiModelProperty("1=满意并加购/下单 0=不满意")
    private Integer accepted;

    @ApiModelProperty("满意动作: cart / order")
    private String acceptedAction;

    @ApiModelProperty("本次 VTON 消耗的 credits 数")
    private Integer creditsConsumed;

    @ApiModelProperty("创建时间")
    private LocalDateTime createdAt;
}
