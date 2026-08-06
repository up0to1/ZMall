package com.hmall.user.controller;

import com.hmall.api.dto.QuotaDeductDTO;
import com.hmall.api.dto.QuotaOperateDTO;
import com.hmall.api.dto.QuotaResultDTO;
import com.hmall.user.service.IQuotaService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * AI 配额服务接口
 * 统一管理 AI 模特（MODEL）和 AI 随心搭（OUTFIT）的配额预扣/确认/回滚。
 */
@Api(tags = "AI配额相关接口")
@RestController
@RequestMapping("/quota")
@RequiredArgsConstructor
public class QuotaController {

    private final IQuotaService quotaService;

    @ApiOperation("预扣配额（原子操作：先免费后付费）")
    @PostMapping("/deduct")
    public QuotaResultDTO deduct(@RequestBody @Validated QuotaDeductDTO dto) {
        return quotaService.deduct(dto.getType(), dto.getId(), dto.getTaskId());
    }

    @ApiOperation("确认消耗（删除冻结记录，不可回滚）")
    @PostMapping("/confirm")
    public void confirm(@RequestBody @Validated QuotaOperateDTO dto) {
        quotaService.confirm(dto.getType(), dto.getId(), dto.getTaskId());
    }

    @ApiOperation("回滚释放（删除冻结记录 + 次数 +1）")
    @PostMapping("/rollback")
    public void rollback(@RequestBody @Validated QuotaOperateDTO dto) {
        quotaService.rollback(dto.getType(), dto.getId(), dto.getTaskId());
    }
}
