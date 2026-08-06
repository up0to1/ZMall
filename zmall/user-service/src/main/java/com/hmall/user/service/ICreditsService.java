package com.hmall.user.service;

import com.hmall.api.dto.CreditsBalanceDTO;
import com.hmall.api.dto.CreditsResultDTO;
import com.hmall.user.enums.QuotaType;

/**
 * AI Credits 积分制配额服务接口（v3）
 *
 * <p>核心设计：
 * <ul>
 *   <li>FIFO 扣减：先扣赠送 credits（30 天有效期，按到期升序），不足部分扣充值 credits（永久）</li>
 *   <li>明细冻结：扣减时把明细（free: [{expireTs, count}, ...], paid: int）写入 Redis frozenKey</li>
 *   <li>原路返还：rollback 时按冻结明细返还（free 返还到原 expireTs 批次，paid 直接累加）</li>
 *   <li>双写对账：Redis 是权威数据源（FIFO 扣减明细在 Redis Hash），DB 仅作对账 + 审计</li>
 * </ul>
 *
 * <p>调用方根据 v3 阶段传入：
 * <ul>
 *   <li>阶段一候选推荐：type=OUTFIT_RECOMMEND, credits=2</li>
 *   <li>阶段二 VTON 生成：type=OUTFIT_VTON, credits=5×N</li>
 * </ul>
 */
public interface ICreditsService {

    /**
     * 预扣 credits（FIFO 原子操作，Lua 脚本保证并发安全）
     *
     * @param type          配额类型: OUTFIT_RECOMMEND / OUTFIT_VTON
     * @param userId        用户ID
     * @param taskId        任务ID（用于冻结记录关联）
     * @param credits       本次需要扣减的 credits 数
     * @return 扣减结果（含扣减后余额）
     */
    CreditsResultDTO deduct(QuotaType type, Long userId, String taskId, int credits);

    /**
     * 确认消耗 credits（删除冻结记录，不返还）
     *
     * <p>v3.1 规则：
     * <ul>
     *   <li>VTON 部分失败：仍调用 confirm（部分失败不退还 credits）</li>
     *   <li>VTON API 故障：调用 rollback（全额退还）</li>
     * </ul>
     */
    void confirm(QuotaType type, Long userId, String taskId);

    /**
     * 回滚 credits（按冻结明细原路返还）
     */
    void rollback(QuotaType type, Long userId, String taskId);

    /**
     * 查询 credits 余额（含过期预警）
     *
     * <p>首次查询时若无账户自动赠送 50 credits（US-AT-32）。
     */
    CreditsBalanceDTO getBalance(Long userId);

    /**
     * 充值 credits（支付成功后调用，幂等校验 payOrderNo）
     *
     * <p>充值 credits 永久有效，写入 Redis String + DB 账户表。
     */
    CreditsBalanceDTO recharge(Long userId, int amountFen, String payOrderNo, Integer packageId);

    /**
     * 激励奖励 credits（US-AT-46/47）
     *
     * <p>每日上限：
     * <ul>
     *   <li>awardType=RATING_PUBLISH：每日 5 次</li>
     *   <li>awardType=REJECT_REASON：每日 3 次</li>
     * </ul>
     *
     * @param awardType 奖励类型: RATING_PUBLISH / REJECT_REASON
     * @param bizRefId  关联业务ID（taskId/modelImageId），用于审计
     * @return 充值后余额（达到每日上限时返回 null，不抛异常）
     */
    CreditsBalanceDTO award(Long userId, int credits, String awardType, String bizRefId);
}
