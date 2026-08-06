package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.Min;
import javax.validation.constraints.NotBlank;
import javax.validation.constraints.NotNull;

/**
 * AI Credits 充值请求
 *
 * <p>充值流程（US-AT-33）：
 * <ol>
 *   <li>前端调 pay-service 创建支付单（金额 = 元）</li>
 *   <li>支付成功后 pay-service 发 MQ 消息（pay.success）</li>
 *   <li>trade-service / user-service 消费 MQ，调 /credits/recharge 接口</li>
 *   <li>CreditsService 增加 paid credits（永久有效）+ 写入 ai_credits_recharge 表</li>
 * </ol>
 *
 * <p>充值汇率：1 元 = 5 credits（{@code RedisConstants.AI_CREDITS_RATE_YUAN_TO_CREDITS}）
 */
@ApiModel(description = "AI Credits 充值请求")
@Data
public class CreditsRechargeDTO {

    @ApiModelProperty(value = "用户ID（已废弃：后端从网关 user-info header 解析，前端无需传入）")
    private Long userId;

    @ApiModelProperty(value = "充值金额（分），1 元 = 100 分", required = true)
    @NotNull(message = "充值金额不能为空")
    @Min(value = 100, message = "最低充值 1 元")
    private Integer amountFen;

    @ApiModelProperty(value = "支付订单号（用于幂等校验）", required = true)
    @NotBlank(message = "支付订单号不能为空")
    private String payOrderNo;

    @ApiModelProperty(value = "充值套餐标识：1=10元50credits / 2=20元110credits / 3=50元300credits / 4=100元650credits")
    private Integer packageId;
}
