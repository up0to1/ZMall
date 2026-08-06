package com.hmall.user.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * AI Credits 账户表
 *
 * <p>每个 user_id 一条记录，汇总 free/paid credits 总额。
 * Redis 是权威数据源（FIFO 扣减明细在 Redis Hash），DB 仅作对账 + 审计。
 *
 * <p>字段说明：
 * <ul>
 *   <li>{@code freeCredits}：赠送 credits 当前余额（与 Redis ai:credits:free:{userId} Hash value 之和一致）</li>
 *   <li>{@code paidCredits}：充值 credits 当前余额（与 Redis ai:credits:paid:{userId} 一致）</li>
 *   <li>{@code totalGifted}：累计赠送 credits（含已过期已消耗）</li>
 *   <li>{@code totalRecharged}：累计充值 credits</li>
 *   <li>{@code totalConsumed}：累计确认消耗 credits（confirm 后累加）</li>
 *   <li>{@code totalRolledBack}：累计回滚 credits（rollback 后累加）</li>
 *   <li>{@code totalAwarded}：累计激励奖励 credits</li>
 *   <li>{@code firstGiftReceived}：是否已领取首次赠送（1=是 0=否，用于前端弹窗提示）</li>
 * </ul>
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("ai_credits_account")
public class AiCreditsAccount implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 用户ID */
    private Long userId;

    /** 赠送 credits 当前余额 */
    private Integer freeCredits;

    /** 充值 credits 当前余额（永久有效） */
    private Integer paidCredits;

    /** 累计赠送 credits（含已过期已消耗） */
    private Integer totalGifted;

    /** 累计充值 credits */
    private Integer totalRecharged;

    /** 累计确认消耗 credits */
    private Integer totalConsumed;

    /** 累计回滚 credits */
    private Integer totalRolledBack;

    /** 累计激励奖励 credits */
    private Integer totalAwarded;

    /** 是否已领取首次赠送：1=是 0=否 */
    private Integer firstGiftReceived;

    /** 状态：1=正常 2=冻结 */
    private Integer status;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
