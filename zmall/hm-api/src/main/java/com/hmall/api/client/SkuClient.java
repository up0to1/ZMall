package com.hmall.api.client;

import com.hmall.api.client.fallback.SkuClientFallbackFactory;
import com.hmall.api.dto.SkuDTO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.Collection;
import java.util.List;

/**
 * SKU 远程调用客户端
 * <p>供 cart-service / trade-service 按 skuId 或 spuId 查询 SKU 信息。
 */
@FeignClient(contextId = "skuClient", value = "item-service", fallbackFactory = SkuClientFallbackFactory.class)
public interface SkuClient {

    /**
     * 按 id 查询单个 SKU
     */
    @GetMapping("/skus/{id}")
    SkuDTO querySkuById(@PathVariable("id") Long id);

    /**
     * 按 id 批量查询 SKU
     */
    @GetMapping("/skus")
    List<SkuDTO> querySkuByIds(@RequestParam("ids") Collection<Long> ids);

    /**
     * 按 SPU(item) id 查询所有 SKU 列表
     */
    @GetMapping("/skus/by-spu/{spuId}")
    List<SkuDTO> querySkusBySpuId(@PathVariable("spuId") Long spuId);

    /**
     * 按 SPU(item) id 查询默认 SKU（is_default=1）
     * <p>用于前端加购时未指定 SKU 的兜底场景。
     */
    @GetMapping("/skus/default-by-spu/{spuId}")
    SkuDTO queryDefaultSkuBySpuId(@PathVariable("spuId") Long spuId);
}
