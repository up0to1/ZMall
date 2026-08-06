package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * AI 随心搭历史记录 DTO（合并 ai_task + ai_outfit_record）
 *
 * 用于"我的搭配历史"页面，展示所有任务状态（含生成中、失败等）。
 */
@ApiModel(description = "AI 随心搭历史记录")
@Data
public class AiOutfitHistoryDTO {

    @ApiModelProperty("ai_outfit_record 主键ID（无记录时为 null）")
    private Long id;

    @ApiModelProperty("任务ID")
    private String taskId;

    @ApiModelProperty("任务状态: PENDING/PROCESSING/SUCCESS/FAILED/TIMEOUT")
    private String taskStatus;

    @ApiModelProperty("任务类型: OUTFIT_AGENT/OUTFIT_PRODUCT/OUTFIT_RECOMMEND/OUTFIT_VTON")
    private String taskType;

    @ApiModelProperty("阶段: candidate/vton/null")
    private String phase;

    @ApiModelProperty("错误信息（失败时）")
    private String errorMsg;

    @ApiModelProperty("套装详情 JSON")
    private String outfitJson;

    @ApiModelProperty("VTON 效果图 URL")
    private String vtonResultUrl;

    @ApiModelProperty("用户原自拍照 URL")
    private String userPhotoUrl;

    @ApiModelProperty("模特图来源: photo/system_pool/ai_generated")
    private String modelImageSource;

    @ApiModelProperty("1=已采纳 0=不满意 2=未操作 null=无记录")
    private Integer accepted;

    @ApiModelProperty("采纳动作: cart/order")
    private String acceptedAction;

    @ApiModelProperty("消耗 credits 数")
    private Integer creditsConsumed;

    @ApiModelProperty("推荐轮次")
    private Integer round;

    @ApiModelProperty("Top3 索引")
    private Integer outfitIndex;

    @ApiModelProperty("任务创建时间")
    private LocalDateTime createdAt;

    @ApiModelProperty("任务完成时间")
    private LocalDateTime finishedAt;
}
