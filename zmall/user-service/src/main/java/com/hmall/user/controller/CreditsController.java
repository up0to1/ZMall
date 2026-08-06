package com.hmall.user.controller;

import com.hmall.api.dto.CreditsAwardDTO;
import com.hmall.api.dto.CreditsBalanceDTO;
import com.hmall.api.dto.CreditsDeductDTO;
import com.hmall.api.dto.CreditsOperateDTO;
import com.hmall.api.dto.CreditsRechargeDTO;
import com.hmall.api.dto.CreditsResultDTO;
import com.hmall.common.utils.UserContext;
import com.hmall.user.enums.QuotaType;
import com.hmall.user.service.ICreditsService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * AI Credits 积分制配额服务接口（v3）
 *
 * <p>接口清单：
 * <ul>
 *   <li>POST /credits/deduct — 预扣（FIFO 扣减）</li>
 *   <li>POST /credits/confirm — 确认消耗（不返还）</li>
 *   <li>POST /credits/rollback — 回滚（按原路返还）</li>
 *   <li>GET /credits/balance/{userId} — 查询余额（含过期预警）</li>
 *   <li>POST /credits/recharge — 充值（支付成功后调）</li>
 *   <li>POST /credits/award — 激励奖励（评分激励）</li>
 * </ul>
 */
@Api(tags = "AI Credits 积分制配额接口")
@RestController
@RequestMapping("/credits")
@RequiredArgsConstructor
public class CreditsController {

    private final ICreditsService creditsService;

    @ApiOperation("预扣 credits（FIFO：先扣赠送 30 天，再扣充值永久）")
    @PostMapping("/deduct")
    public CreditsResultDTO deduct(@RequestBody @Validated CreditsDeductDTO dto) {
        QuotaType type = QuotaType.of(dto.getType());
        return creditsService.deduct(type, dto.getUserId(), dto.getTaskId(), dto.getCredits());
    }

    @ApiOperation("确认消耗 credits（删除冻结记录，不返还）")
    @PostMapping("/confirm")
    public void confirm(@RequestBody @Validated CreditsOperateDTO dto) {
        QuotaType type = QuotaType.of(dto.getType());
        creditsService.confirm(type, dto.getUserId(), dto.getTaskId());
    }

    @ApiOperation("回滚 credits（按冻结明细原路返还）")
    @PostMapping("/rollback")
    public void rollback(@RequestBody @Validated CreditsOperateDTO dto) {
        QuotaType type = QuotaType.of(dto.getType());
        creditsService.rollback(type, dto.getUserId(), dto.getTaskId());
    }

    @ApiOperation("查询 credits 余额（含过期预警）")
    @GetMapping("/balance/{userId}")
    public CreditsBalanceDTO balance(@PathVariable("userId") Long userId) {
        return creditsService.getBalance(userId);
    }

    @ApiOperation("充值 credits（支付成功后调，幂等校验 payOrderNo）")
    @PostMapping("/recharge")
    public CreditsBalanceDTO recharge(@RequestBody @Validated CreditsRechargeDTO dto) {
        // F7 安全修复：userId 从网关 user-info header 解析，不信任前端传入
        Long userId = UserContext.getUser();
        return creditsService.recharge(userId, dto.getAmountFen(),
                dto.getPayOrderNo(), dto.getPackageId());
    }

    @ApiOperation("激励奖励 credits（评分激励）")
    @PostMapping("/award")
    public CreditsBalanceDTO award(@RequestBody @Validated CreditsAwardDTO dto) {
        return creditsService.award(dto.getUserId(), dto.getCredits(),
                dto.getAwardType(), dto.getBizRefId());
    }
}
