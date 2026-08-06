package com.hmall.item.controller;

import com.hmall.api.dto.SkuDTO;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.CollUtils;
import com.hmall.item.domain.po.Sku;
import com.hmall.item.service.ISkuService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.Collection;
import java.util.List;

/**
 * SKU 相关接口
 * <p>供 cart-service / trade-service 通过 Feign 调用，也供前台商品详情页查询 SKU 列表。
 */
@Api(tags = "SKU 管理接口")
@RestController
@RequestMapping("/skus")
@RequiredArgsConstructor
public class SkuController {

    private final ISkuService skuService;

    @ApiOperation("按 id 查询 SKU")
    @GetMapping("/{id}")
    public SkuDTO querySkuById(@PathVariable("id") Long id) {
        Sku sku = skuService.getById(id);
        return sku == null ? null : BeanUtils.copyBean(sku, SkuDTO.class);
    }

    @ApiOperation("按 id 批量查询 SKU")
    @GetMapping
    public List<SkuDTO> querySkuByIds(@RequestParam("ids") Collection<Long> ids) {
        List<Sku> skus = skuService.querySkuByIds(ids);
        if (CollUtils.isEmpty(skus)) {
            return CollUtils.emptyList();
        }
        return BeanUtils.copyList(skus, SkuDTO.class);
    }

    @ApiOperation("按 SPU(item) id 查询所有 SKU 列表")
    @GetMapping("/by-spu/{spuId}")
    public List<SkuDTO> querySkusBySpuId(@PathVariable("spuId") Long spuId) {
        List<Sku> skus = skuService.querySkusBySpuId(spuId);
        if (CollUtils.isEmpty(skus)) {
            return CollUtils.emptyList();
        }
        return BeanUtils.copyList(skus, SkuDTO.class);
    }

    @ApiOperation("按 SPU(item) id 查询默认 SKU")
    @GetMapping("/default-by-spu/{spuId}")
    public SkuDTO queryDefaultSkuBySpuId(@PathVariable("spuId") Long spuId) {
        Sku sku = skuService.queryDefaultSkuBySpuId(spuId);
        return sku == null ? null : BeanUtils.copyBean(sku, SkuDTO.class);
    }
}
