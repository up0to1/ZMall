package com.hmall.api.client.fallback;

import com.hmall.api.client.SkuClient;
import com.hmall.api.dto.SkuDTO;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.utils.CollUtils;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;

import java.util.Collection;
import java.util.List;

@Slf4j
public class SkuClientFallbackFactory implements FallbackFactory<SkuClient> {

    @Override
    public SkuClient create(Throwable cause) {
        return new SkuClient() {
            @Override
            public SkuDTO querySkuById(Long id) {
                log.error("远程调用SkuClient#querySkuById方法出现异常，参数：{}", id, cause);
                return null;
            }

            @Override
            public List<SkuDTO> querySkuByIds(Collection<Long> ids) {
                log.error("远程调用SkuClient#querySkuByIds方法出现异常，参数：{}", ids, cause);
                return CollUtils.emptyList();
            }

            @Override
            public List<SkuDTO> querySkusBySpuId(Long spuId) {
                log.error("远程调用SkuClient#querySkusBySpuId方法出现异常，参数：{}", spuId, cause);
                return CollUtils.emptyList();
            }

            @Override
            public SkuDTO queryDefaultSkuBySpuId(Long spuId) {
                log.error("远程调用SkuClient#queryDefaultSkuBySpuId方法出现异常，参数：{}", spuId, cause);
                throw new BizIllegalException("商品服务不可用，查询默认 SKU 失败", cause);
            }
        };
    }
}
