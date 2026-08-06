package com.hmall.item.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmall.item.domain.po.Sku;

import java.util.Collection;
import java.util.List;

/**
 * SKU 服务接口
 */
public interface ISkuService extends IService<Sku> {

    /**
     * 按 id 批量查询 SKU
     */
    List<Sku> querySkuByIds(Collection<Long> ids);

    /**
     * 按 SPU(item) id 查询所有 SKU 列表
     */
    List<Sku> querySkusBySpuId(Long spuId);

    /**
     * 按 SPU(item) id 查询默认 SKU（is_default=1）
     * <p>用于前端加购未指定 SKU 的兜底场景；若无默认 SKU 则返回 null。
     */
    Sku queryDefaultSkuBySpuId(Long spuId);
}
