package com.hmall.api.client.fallback;

import com.hmall.api.client.UserClient;
import com.hmall.api.dto.DeductMoneyDTO;
import com.hmall.common.exception.BizIllegalException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;

@Slf4j
public class UserClientFallbackFactory implements FallbackFactory<UserClient> {

    @Override
    public UserClient create(Throwable cause) {
        return new UserClient() {
            @Override
            public void deductMoney(DeductMoneyDTO dto) {
                log.error("远程调用UserClient#deductMoney方法出现异常，参数：{}", dto, cause);
                throw new BizIllegalException("用户服务不可用，扣款失败", cause);
            }

            @Override
            public void refundMoney(Long userId, Integer amount) {
                log.error("远程调用UserClient#refundMoney方法出现异常，userId={}，amount={}", userId, amount, cause);
                throw new BizIllegalException("用户服务不可用，退款失败", cause);
            }
        };
    }
}
