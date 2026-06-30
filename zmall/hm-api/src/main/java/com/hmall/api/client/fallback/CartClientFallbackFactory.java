package com.hmall.api.client.fallback;

import com.hmall.api.client.CartClient;
import com.hmall.common.exception.BizIllegalException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;

import java.util.Collection;

@Slf4j
public class CartClientFallbackFactory implements FallbackFactory<CartClient> {

    @Override
    public CartClient create(Throwable cause) {
        return new CartClient() {
            @Override
            public void deleteCartItemByIds(Collection<Long> ids) {
                log.error("远程调用CartClient#deleteCartItemByIds方法出现异常，参数：{}", ids, cause);
                throw new BizIllegalException("购物车服务不可用，删除购物车失败", cause);
            }
        };
    }
}
