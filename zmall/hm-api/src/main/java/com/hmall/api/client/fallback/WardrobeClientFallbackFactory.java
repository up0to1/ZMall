package com.hmall.api.client.fallback;

import com.hmall.api.client.WardrobeClient;
import com.hmall.api.dto.WardrobeDTO;
import com.hmall.common.utils.CollUtils;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;

import java.util.Collection;
import java.util.List;

@Slf4j
public class WardrobeClientFallbackFactory implements FallbackFactory<WardrobeClient> {

    @Override
    public WardrobeClient create(Throwable cause) {
        return new WardrobeClient() {
            @Override
            public List<WardrobeDTO> queryUserWardrobe(Long userId) {
                log.error("远程调用WardrobeClient#queryUserWardrobe方法出现异常，参数：{}", userId, cause);
                return CollUtils.emptyList();
            }

            @Override
            public List<WardrobeDTO> queryWardrobeByIds(Collection<Long> ids) {
                log.error("远程调用WardrobeClient#queryWardrobeByIds方法出现异常，参数：{}", ids, cause);
                return CollUtils.emptyList();
            }

            @Override
            public List<Long> queryMyWardrobeItemIds(Long userId) {
                log.error("远程调用WardrobeClient#queryMyWardrobeItemIds方法出现异常，参数：{}", userId, cause);
                return CollUtils.emptyList();
            }

            @Override
            public WardrobeDTO addWardrobeOutfit(WardrobeDTO dto) {
                // v3.1：AI 搭配效果图写入衣橱失败 → 返回 null，调用方（Python ai-outfit）应容忍失败
                log.error("远程调用WardrobeClient#addWardrobeOutfit方法出现异常（不阻塞 accept 主流程），参数：userId={}, recordId={}",
                        dto == null ? null : dto.getUserId(), dto == null ? null : dto.getRecordId(), cause);
                return null;
            }

            @Override
            public void removeByRecord(Long recordId) {
                // 取消满意/改不满意联动删除衣橱失败 → 仅告警，不影响记录状态更新主流程
                log.error("远程调用WardrobeClient#removeByRecord方法出现异常，参数：recordId={}", recordId, cause);
            }
        };
    }
}
