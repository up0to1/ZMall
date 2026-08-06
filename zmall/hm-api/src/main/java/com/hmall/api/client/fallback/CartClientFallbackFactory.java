package com.hmall.api.client.fallback;

import com.hmall.api.client.CartClient;
import com.hmall.api.dto.CartBatchDTO;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.utils.CollUtils;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;

import java.util.Collection;
import java.util.List;

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

            @Override
            public void batchAdd2Cart(CartBatchDTO dto) {
                log.error("远程调用CartClient#batchAdd2Cart方法出现异常", cause);
                throw new BizIllegalException("购物车服务不可用，套装加购失败", cause);
            }

            @Override
            public List<Long> queryMyCartItemIds(Long userId) {
                log.error("远程调用CartClient#queryMyCartItemIds方法出现异常，参数：{}", userId, cause);
                return CollUtils.emptyList();
            }
        };
    }
}
