package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * AI Credits 预扣结果（含扣减后余额，前端用于刷新 CreditsBar）
 *
 * <p>v3 设计：WS 推送的 creditsBalance 仅用于展示刷新，每次发起扣费操作前调 GET /credits/balance 获取最新余额。
 */
@ApiModel(description = "AI Credits 预扣结果")
@Data
@NoArgsConstructor
@AllArgsConstructor
public class CreditsResultDTO {

    @ApiModelProperty(value = "是否成功")
    private Boolean success;

    @ApiModelProperty(value = "提示信息")
    private String msg;

    @ApiModelProperty(value = "本次扣减的 credits 数")
    private Integer creditsConsumed;

    @ApiModelProperty(value = "扣减后总可用 credits（free + paid）")
    private Integer balance;

    @ApiModelProperty(value = "扣减后赠送 credits 余额（30 天有效期）")
    private Integer freeBalance;

    @ApiModelProperty(value = "扣减后充值 credits 余额（永久）")
    private Integer paidBalance;

    @ApiModelProperty(value = "最近即将过期的赠送 credits 数（剩余 ≤3 天时返回，否则 null）")
    private Integer expiringSoon;

    public static CreditsResultDTO success(int consumed, int balance, int freeBalance, int paidBalance) {
        CreditsResultDTO dto = new CreditsResultDTO();
        dto.success = true;
        dto.msg = "预扣成功";
        dto.creditsConsumed = consumed;
        dto.balance = balance;
        dto.freeBalance = freeBalance;
        dto.paidBalance = paidBalance;
        return dto;
    }

    public static CreditsResultDTO refused() {
        CreditsResultDTO dto = new CreditsResultDTO();
        dto.success = false;
        dto.msg = "AI credits 余额不足";
        return dto;
    }
}
