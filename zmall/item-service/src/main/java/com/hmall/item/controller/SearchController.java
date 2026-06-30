package com.hmall.item.controller;


import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.utils.BeanUtils;
import com.hmall.api.dto.ItemDTO;
import com.hmall.item.domain.po.Item;
import com.hmall.item.domain.query.ItemPageQuery;
import com.hmall.item.service.IItemService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@Api(tags = "搜索相关接口")
@RestController
@RequestMapping("/search")
@RequiredArgsConstructor
public class SearchController {

    private final IItemService itemService;

    @ApiOperation("搜索商品")
    @GetMapping("/list")
    public PageDTO<ItemDTO> search(ItemPageQuery query) {
        // 分页查询
        Page<Item> page = new Page<>(query.getPageNo(), query.getPageSize());
        // 排序
        if (StrUtil.isNotBlank(query.getSortBy())) {
            if (query.getIsAsc()) {
                page.setAsc(query.getSortBy());
            } else {
                page.setDesc(query.getSortBy());
            }
        }
        Page<Item> result = itemService.lambdaQuery()
                .like(StrUtil.isNotBlank(query.getKey()), Item::getName, query.getKey())
                .eq(StrUtil.isNotBlank(query.getBrand()), Item::getBrand, query.getBrand())
                .eq(StrUtil.isNotBlank(query.getCategory()), Item::getCategory, query.getCategory())
                .eq(Item::getStatus, 1)
                .between(query.getMaxPrice() != null, Item::getPrice, query.getMinPrice(), query.getMaxPrice())
                .page(page);
        // 封装并返回
        return PageDTO.of(result.getTotal(), result.getPages(), BeanUtils.copyList(result.getRecords(), ItemDTO.class));
    }
}
