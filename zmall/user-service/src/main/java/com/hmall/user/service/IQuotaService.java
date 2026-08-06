package com.hmall.user.service;

import com.hmall.api.dto.QuotaResultDTO;

/**
 * AI 配额服务接口
 */
public interface IQuotaService {

    /**
     * 预扣配额（原子操作：先免费后付费，Lua 脚本保证并发安全）
     *
     * @param type   配额类型: MODEL / OUTFIT
     * @param id     配额主体ID（MODEL时为shopId，OUTFIT时为userId）
     * @param taskId 任务ID（用于冻结记录关联）
     * @return 预扣结果
     */
    QuotaResultDTO deduct(String type, Long id, String taskId);

    /**
     * 确认消耗（删除冻结记录，不可回滚）
     */
    void confirm(String type, Long id, String taskId);

    /**
     * 回滚释放（删除冻结记录 + 次数 +1）
     */
    void rollback(String type, Long id, String taskId);
}
