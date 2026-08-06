package com.hmall.api.client;

import com.hmall.api.client.fallback.QuotaClientFallbackFactory;
import com.hmall.api.dto.CreditsAwardDTO;
import com.hmall.api.dto.CreditsBalanceDTO;
import com.hmall.api.dto.CreditsDeductDTO;
import com.hmall.api.dto.CreditsOperateDTO;
import com.hmall.api.dto.CreditsRechargeDTO;
import com.hmall.api.dto.CreditsResultDTO;
import com.hmall.api.dto.QuotaDeductDTO;
import com.hmall.api.dto.QuotaOperateDTO;
import com.hmall.api.dto.QuotaResultDTO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

/**
 * AI 配额服务 Feign 客户端
 *
 * <p>包含两套接口：
 * <ul>
 *   <li>旧版次数制：/quota/deduct /quota/confirm /quota/rollback（仅 MODEL/OUTFIT 商品驱动使用）</li>
 *   <li>v3 credits 积分制：/credits/deduct /credits/confirm /credits/rollback /credits/balance /credits/recharge /credits/award</li>
 * </ul>
 */
@FeignClient(contextId = "quotaClient", value = "user-service", fallbackFactory = QuotaClientFallbackFactory.class)
public interface QuotaClient {

    // ===== 旧版次数制配额（MODEL / OUTFIT 商品驱动）=====

    /**
     * 预扣配额（原子操作：先免费后付费，Lua 脚本保证并发安全）
     */
    @PostMapping("/quota/deduct")
    QuotaResultDTO deduct(@RequestBody QuotaDeductDTO dto);

    /**
     * 确认消耗（删除冻结记录，不可回滚）
     */
    @PostMapping("/quota/confirm")
    void confirm(@RequestBody QuotaOperateDTO dto);

    /**
     * 回滚释放（删除冻结记录 + 次数 +1）
     */
    @PostMapping("/quota/rollback")
    void rollback(@RequestBody QuotaOperateDTO dto);

    // ===== v3 credits 积分制（OUTFIT_RECOMMEND / OUTFIT_VTON）=====

    /**
     * v3 预扣 credits（FIFO：先扣赠送 30 天，再扣充值永久）
     *
     * <p>调用方根据阶段传：
     * <ul>
     *   <li>阶段一候选推荐：type=OUTFIT_RECOMMEND, credits=2</li>
     *   <li>阶段二 VTON 生成：type=OUTFIT_VTON, credits=5×N</li>
     * </ul>
     */
    @PostMapping("/credits/deduct")
    CreditsResultDTO creditsDeduct(@RequestBody CreditsDeductDTO dto);

    /**
     * v3 确认消耗 credits（删除冻结记录，不返还）
     */
    @PostMapping("/credits/confirm")
    void creditsConfirm(@RequestBody CreditsOperateDTO dto);

    /**
     * v3 回滚 credits（按冻结明细原路返还：free 返还到原 expireTs 批次，paid 直接累加）
     */
    @PostMapping("/credits/rollback")
    void creditsRollback(@RequestBody CreditsOperateDTO dto);

    /**
     * v3 查询 credits 余额（每次发起扣费操作前调，权威余额以 Redis 为准）
     */
    @GetMapping("/credits/balance/{userId}")
    CreditsBalanceDTO creditsBalance(@PathVariable("userId") Long userId);

    /**
     * v3 充值 credits（支付成功后调，幂等校验 payOrderNo）
     */
    @PostMapping("/credits/recharge")
    CreditsBalanceDTO creditsRecharge(@RequestBody CreditsRechargeDTO dto);

    /**
     * v3 激励奖励 credits（评分 ≥4★+发布 / 拒绝原因 ≥20 字）
     */
    @PostMapping("/credits/award")
    CreditsBalanceDTO creditsAward(@RequestBody CreditsAwardDTO dto);
}
