package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

/**
 * AI 随心搭结果回流消息（Python → Java user-service 消费）
 *
 * <p>v3 拆分：阶段一候选推荐 / 阶段二 VTON 生成 走不同 type + phase：
 * <ul>
 *   <li>OUTFIT_PRODUCT（旧版商品驱动）→ phase=null</li>
 *   <li>OUTFIT_CANDIDATE（v3 阶段一）→ phase=candidate</li>
 *   <li>OUTFIT_VTON（v3 阶段二）→ phase=vton</li>
 * </ul>
 *
 * <p>user-service 消费时按 phase 路由：
 * <ul>
 *   <li>phase=null → 走旧版 QuotaService.confirm/rollback（次数制）</li>
 *   <li>phase=candidate/vton → 走 CreditsService.confirm/rollback（credits 积分制）</li>
 * </ul>
 *
 * <p>v3.1 失败规则由 Python 侧 _async_vton 做权威判定：
 * <ul>
 *   <li>阶段二 VTON 部分失败 → Python 推 SUCCESS → Java confirm（不退还 credits）</li>
 *   <li>阶段二 VTON 全部失败 / API 故障 → Python 推 FAILED → Java rollback（全额退还）</li>
 * </ul>
 * Java 侧无需读取 partialFailures/creditsConsumed 字段，已删除。
 */
@ApiModel(description = "AI 随心搭结果回流消息")
@Data
public class AiOutfitResultMessage {

    @ApiModelProperty("任务ID")
    private String taskId;

    @ApiModelProperty("任务类型: OUTFIT_PRODUCT（旧版商品驱动）/ OUTFIT_CANDIDATE（v3阶段一）/ OUTFIT_VTON（v3阶段二）")
    private String type;

    @ApiModelProperty("用户ID")
    private Long userId;

    @ApiModelProperty("状态: SUCCESS / FAILED")
    private String status;

    @ApiModelProperty("错误信息（失败时）")
    private String errorMsg;

    @ApiModelProperty("v3 阶段标识: candidate / vton / null（旧版商品驱动）")
    private String phase;
}
