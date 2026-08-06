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
 * AI Credits 充值记录表
 *
 * <p>记录每次充值明细，支持对账 + 幂等（{@code payOrderNo} 唯一索引）。
 * 充值 credits 永久有效，不写入 Redis Hash（Hash 仅存赠送 credits 的过期批次），
 * 而是写入 Redis String（ai:credits:paid:{userId}）。
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("ai_credits_recharge")
public class AiCreditsRecharge implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 用户ID */
    private Long userId;

    /** 充值金额（分） */
    private Integer amountFen;

    /** 充值 credits 数 */
    private Integer credits;

    /** 支付订单号（幂等校验用，唯一索引） */
    private String payOrderNo;

    /** 套餐标识：1=10元50credits / 2=20元110credits / 3=50元300credits / 4=100元650credits */
    private Integer packageId;

    /** 状态：1=成功 2=失败 */
    private Integer status;

    private LocalDateTime createTime;
}
