package com.hmall.api.client.fallback;

import com.hmall.api.client.BodyProfileClient;
import com.hmall.api.dto.BodyProfileDTO;
import com.hmall.common.utils.CollUtils;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;

import java.util.List;

/**
 * BodyProfileClient 降级工厂
 *
 * <p>降级策略：查询失败返回空，调用方（item-service 尺码推荐）应容忍失败，
 * 无身体信息时跳过尺码推荐或返回"无法推荐尺码"提示。
 *
 * @author hmall
 * @since 2026-07-27
 */
@Slf4j
public class BodyProfileClientFallbackFactory implements FallbackFactory<BodyProfileClient> {

    @Override
    public BodyProfileClient create(Throwable cause) {
        return new BodyProfileClient() {
            @Override
            public BodyProfileDTO queryBodyProfile(Long id) {
                log.error("远程调用BodyProfileClient#queryBodyProfile方法出现异常，参数：{}", id, cause);
                return null;
            }

            @Override
            public List<BodyProfileDTO> queryUserBodyProfiles(Long userId) {
                log.error("远程调用BodyProfileClient#queryUserBodyProfiles方法出现异常，参数：{}", userId, cause);
                return CollUtils.emptyList();
            }
        };
    }
}
