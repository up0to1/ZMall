package com.hmall.item.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.item.domain.po.Sku;
import com.hmall.item.mapper.SkuMapper;
import com.hmall.item.service.ISkuService;
import org.springframework.stereotype.Service;

import java.util.Collection;
import java.util.List;

/**
 * SKU 服务实现类
 */
@Service
public class SkuServiceImpl extends ServiceImpl<SkuMapper, Sku> implements ISkuService {

    @Override
    public List<Sku> querySkuByIds(Collection<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return List.of();
        }
        return listByIds(ids);
    }

    @Override
    public List<Sku> querySkusBySpuId(Long spuId) {
        if (spuId == null) {
            return List.of();
        }
        return lambdaQuery().eq(Sku::getSpuId, spuId).list();
    }

    @Override
    public Sku queryDefaultSkuBySpuId(Long spuId) {
        if (spuId == null) {
            return null;
        }
        // 优先取 is_default=1 的 SKU
        Sku sku = lambdaQuery()
                .eq(Sku::getSpuId, spuId)
                .eq(Sku::getIsDefault, 1)
                .one();
        if (sku != null) {
            return sku;
        }
        // 兜底：无默认 SKU 时取第一条（兼容单 SKU 商品未设默认的场景）
        return lambdaQuery()
                .eq(Sku::getSpuId, spuId)
                .orderByAsc(Sku::getId)
                .last("LIMIT 1")
                .one();
    }
}
