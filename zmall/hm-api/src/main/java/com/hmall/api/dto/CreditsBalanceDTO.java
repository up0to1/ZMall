package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * AI Credits 余额查询响应
 *
 * <p>GET /credits/balance 接口返回。前端 CreditsBar 组件据此渲染：
 * <ul>
 *   <li>总余额 = freeBalance + paidBalance</li>
 *   <li>展示"即将过期 X credits"提示（expiringSoon &gt; 0 时高亮）</li>
 *   <li>展示"首次赠送 Y credits 已到账"提示（firstGiftReceived=true 时一次性弹窗）</li>
 * </ul>
 */
@ApiModel(description = "AI Credits 余额")
@Data
public class CreditsBalanceDTO {

    @ApiModelProperty(value = "用户ID")
    private Long userId;

    @ApiModelProperty(value = "总可用 credits（free + paid）")
    private Integer balance;

    @ApiModelProperty(value = "赠送 credits 余额（30 天有效期）")
    private Integer freeBalance;

    @ApiModelProperty(value = "充值 credits 余额（永久）")
    private Integer paidBalance;

    @ApiModelProperty(value = "最近即将过期的赠送 credits 数（剩余 ≤3 天时返回，否则 0）")
    private Integer expiringSoon;

    @ApiModelProperty(value = "最近过期时间（expiringSoon>0 时返回）")
    private LocalDateTime nearestExpiry;

    @ApiModelProperty(value = "是否已领取首次赠送（用于前端弹窗提示）")
    private Boolean firstGiftReceived;

    @ApiModelProperty(value = "钱包余额（user.balance，单位：分）。充值 credits 时从此余额扣减")
    private Integer walletBalance;
}
