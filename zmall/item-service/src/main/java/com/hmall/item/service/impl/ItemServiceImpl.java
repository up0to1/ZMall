package com.hmall.item.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.utils.BeanUtils;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.OrderDetailDTO;
import com.hmall.item.domain.po.Item;
import com.hmall.item.mapper.ItemMapper;
import com.hmall.item.service.IItemService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Collection;
import java.util.List;

@Slf4j
@Service
public class ItemServiceImpl extends ServiceImpl<ItemMapper, Item> implements IItemService {

    @Override
    @Transactional
    public void deductStock(List<OrderDetailDTO> items) {
        for (OrderDetailDTO item : items) {
            int rows = baseMapper.updateStock(item);
            if (rows == 0) {
                throw new BizIllegalException("库存不足！");
            }
        }
    }

    @Override
    public List<ItemDTO> queryItemByIds(Collection<Long> ids) {
        return BeanUtils.copyList(listByIds(ids), ItemDTO.class);
    }

    @Override
    @Transactional
    public void restoreStock(List<OrderDetailDTO> items) {
        for (OrderDetailDTO item : items) {
            // 商品已被删除则跳过，下架状态仍可恢复库存
            Item existItem = getById(item.getItemId());
            if (existItem == null) {
                log.warn("恢复库存跳过，商品已删除，itemId={}", item.getItemId());
                continue;
            }
            int rows = baseMapper.restoreStock(item);
            if (rows == 0) {
                log.warn("恢复库存未生效，itemId={}", item.getItemId());
            }
        }
    }

    @Override
    public Page<Item> queryMerchantPage(int page, int size, String keyword, Long merchantId) {
        LambdaQueryWrapper<Item> wrapper = new LambdaQueryWrapper<>();
        wrapper.ne(Item::getStatus, 3);
        if (merchantId != null) {
            wrapper.eq(Item::getCreater, merchantId);
        }
        if (keyword != null && !keyword.isEmpty()) {
            wrapper.like(Item::getName, keyword);
        }
        wrapper.orderByAsc(Item::getStock);
        return page(new Page<>(page, size), wrapper);
    }

    @Override
    public Page<Item> queryAdminPage(int page, int size, String name, Integer status, Integer itemType, Long merchantId) {
        LambdaQueryWrapper<Item> wrapper = new LambdaQueryWrapper<>();
        if (merchantId != null) {
            wrapper.eq(Item::getCreater, merchantId);
        }
        if (name != null && !name.isEmpty()) {
            wrapper.like(Item::getName, name);
        }
        if (status != null) {
            wrapper.eq(Item::getStatus, status);
        } else {
            // 默认不显示已删除的商品
            wrapper.ne(Item::getStatus, 3);
        }
        if (itemType != null) {
            wrapper.eq(Item::getItemType, itemType);
        }
        wrapper.orderByDesc(Item::getUpdateTime);
        return page(new Page<>(page, size), wrapper);
    }

    @Override
    public List<Item> getLowStockItems(int threshold, Long merchantId) {
        LambdaQueryWrapper<Item> wrapper = new LambdaQueryWrapper<Item>()
                .ne(Item::getStatus, 3)
                .le(Item::getStock, threshold);
        if (merchantId != null) {
            wrapper.eq(Item::getCreater, merchantId);
        }
        return list(wrapper.orderByAsc(Item::getStock));
    }

    @Override
    @Transactional
    public void adjustStock(Long itemId, int targetStock) {
        if (targetStock < 0) {
            throw new BadRequestException("库存不能为负数");
        }
        Item item = getById(itemId);
        if (item == null) {
            throw new BadRequestException("商品不存在");
        }
        lambdaUpdate()
                .eq(Item::getId, itemId)
                .set(Item::getStock, targetStock)
                .update();
        log.info("库存调整: itemId={}, 原库存={}, 新库存={}", itemId, item.getStock(), targetStock);
    }

    @Override
    public long countByStatus(Integer status) {
        return count(new LambdaQueryWrapper<Item>().eq(Item::getStatus, status));
    }
}
