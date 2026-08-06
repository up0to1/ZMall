package com.hmall.api.client.fallback;

import com.hmall.api.client.QuotaClient;
import com.hmall.api.dto.CreditsAwardDTO;
import com.hmall.api.dto.CreditsBalanceDTO;
import com.hmall.api.dto.CreditsDeductDTO;
import com.hmall.api.dto.CreditsOperateDTO;
import com.hmall.api.dto.CreditsRechargeDTO;
import com.hmall.api.dto.CreditsResultDTO;
import com.hmall.api.dto.QuotaDeductDTO;
import com.hmall.api.dto.QuotaOperateDTO;
import com.hmall.api.dto.QuotaResultDTO;
import com.hmall.common.exception.BizIllegalException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;

/**
 * AI 配额服务降级工厂
 *
 * <p>降级策略：
 * <ul>
 *   <li>预扣（deduct/creditsDeduct）：抛 BizIllegalException 快速失败，避免配额服务挂了还放行任务（超卖风险）</li>
 *   <li>确认/回滚（confirm/rollback/creditsConfirm/creditsRollback）：抛异常让调用方 catch 记录 failed 指标</li>
 *   <li>余额/充值/奖励（balance/recharge/award）：抛异常让调用方感知，调用方根据场景降级</li>
 * </ul>
 */
@Slf4j
public class QuotaClientFallbackFactory implements FallbackFactory<QuotaClient> {

    @Override
    public QuotaClient create(Throwable cause) {
        log.error("远程调用QuotaClient出现异常", cause);
        return new QuotaClient() {
            @Override
            public QuotaResultDTO deduct(QuotaDeductDTO dto) {
                throw new BizIllegalException("配额服务不可用，预扣失败", cause);
            }

            @Override
            public void confirm(QuotaOperateDTO dto) {
                log.error("配额确认失败，任务可能残留冻结记录: taskId={}", dto.getTaskId(), cause);
                throw new BizIllegalException("配额确认失败（配额服务不可用）: taskId=" + dto.getTaskId(), cause);
            }

            @Override
            public void rollback(QuotaOperateDTO dto) {
                log.error("配额回滚失败，额度可能被吞（需人工补救）: taskId={}", dto.getTaskId(), cause);
                throw new BizIllegalException("配额回滚失败（配额服务不可用，额度需人工补救）: taskId=" + dto.getTaskId(), cause);
            }

            // ===== v3 credits 降级 =====

            @Override
            public CreditsResultDTO creditsDeduct(CreditsDeductDTO dto) {
                throw new BizIllegalException("Credits 服务不可用，预扣失败", cause);
            }

            @Override
            public void creditsConfirm(CreditsOperateDTO dto) {
                log.error("Credits 确认失败，任务可能残留冻结记录: taskId={}", dto.getTaskId(), cause);
                throw new BizIllegalException("Credits 确认失败（服务不可用）: taskId=" + dto.getTaskId(), cause);
            }

            @Override
            public void creditsRollback(CreditsOperateDTO dto) {
                log.error("Credits 回滚失败，额度可能被吞（需人工补救）: taskId={}", dto.getTaskId(), cause);
                throw new BizIllegalException("Credits 回滚失败（服务不可用，额度需人工补救）: taskId=" + dto.getTaskId(), cause);
            }

            @Override
            public CreditsBalanceDTO creditsBalance(Long userId) {
                log.error("Credits 余额查询失败: userId={}", userId, cause);
                // 余额查询失败时返回 -1 余额，让前端展示"服务不可用"
                CreditsBalanceDTO fallback = new CreditsBalanceDTO();
                fallback.setUserId(userId);
                fallback.setBalance(-1);
                fallback.setFreeBalance(0);
                fallback.setPaidBalance(0);
                fallback.setExpiringSoon(0);
                fallback.setFirstGiftReceived(false);
                return fallback;
            }

            @Override
            public CreditsBalanceDTO creditsRecharge(CreditsRechargeDTO dto) {
                log.error("Credits 充值失败: userId={}, payOrderNo={}", dto.getUserId(), dto.getPayOrderNo(), cause);
                throw new BizIllegalException("Credits 充值失败（服务不可用，请勿重复支付）: " + dto.getPayOrderNo(), cause);
            }

            @Override
            public CreditsBalanceDTO creditsAward(CreditsAwardDTO dto) {
                log.error("Credits 奖励失败: userId={}, awardType={}", dto.getUserId(), dto.getAwardType(), cause);
                // 奖励失败不抛异常，避免阻塞主流程（评分激励是次要功能）
                CreditsBalanceDTO fallback = new CreditsBalanceDTO();
                fallback.setUserId(dto.getUserId());
                fallback.setBalance(-1);
                return fallback;
            }
        };
    }
}
