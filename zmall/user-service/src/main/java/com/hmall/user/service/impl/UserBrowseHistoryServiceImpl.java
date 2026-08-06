package com.hmall.user.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.api.client.ItemClient;
import com.hmall.api.dto.ItemDTO;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.utils.UserContext;
import com.hmall.user.domain.po.UserBrowseHistory;
import com.hmall.user.domain.vo.UserBrowseHistoryVO;
import com.hmall.user.mapper.UserBrowseHistoryMapper;
import com.hmall.user.service.IUserBrowseHistoryService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 用户浏览记录服务实现
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserBrowseHistoryServiceImpl extends ServiceImpl<UserBrowseHistoryMapper, UserBrowseHistory> implements IUserBrowseHistoryService {

    private final ItemClient itemClient;

    @Override
    public PageDTO<UserBrowseHistoryVO> queryMyHistory(Integer pageNum, Integer pageSize) {
        Long userId = UserContext.getUser();
        // 分页查询当前用户的浏览记录，按 last_viewed_at 倒序
        Page<UserBrowseHistory> page = new Page<>(pageNum, pageSize);
        page = this.page(page,
                new LambdaQueryWrapper<UserBrowseHistory>()
                        .eq(UserBrowseHistory::getUserId, userId)
                        .orderByDesc(UserBrowseHistory::getLastViewedAt));
        List<UserBrowseHistory> records = page.getRecords();
        if (records.isEmpty()) {
            return PageDTO.empty(page.getTotal(), page.getPages());
        }
        // 批量拉取商品信息（itemName/itemImage/itemPrice/shopId）
        Set<Long> itemIds = records.stream().map(UserBrowseHistory::getItemId).collect(Collectors.toSet());
        Map<Long, ItemDTO> itemMap = fetchItems(itemIds);
        // 组装 VO
        List<UserBrowseHistoryVO> voList = records.stream().map(h -> toVO(h, itemMap)).collect(Collectors.toList());
        return PageDTO.of(page.getTotal(), page.getPages(), voList);
    }

    @Override
    public void recordView(Long itemId, String viewSource, Integer viewDuration) {
        Long userId = UserContext.getUser();
        // 查询是否已存在同一商品的浏览记录
        UserBrowseHistory existing = this.getOne(
                new LambdaQueryWrapper<UserBrowseHistory>()
                        .eq(UserBrowseHistory::getUserId, userId)
                        .eq(UserBrowseHistory::getItemId, itemId));
        LocalDateTime now = LocalDateTime.now();
        if (existing != null) {
            // 已存在：view_count+1，更新 last_viewed_at / view_duration / view_source
            existing.setViewCount(existing.getViewCount() + 1)
                    .setLastViewedAt(now)
                    .setViewSource(viewSource);
            if (viewDuration != null && viewDuration > 0) {
                existing.setViewDuration(viewDuration);
            }
            this.updateById(existing);
            return;
        }
        // 不存在：新增记录，拉取商品的 shopId 和 category（失败不阻塞）
        UserBrowseHistory history = new UserBrowseHistory()
                .setUserId(userId)
                .setItemId(itemId)
                .setViewSource(viewSource)
                .setViewDuration(viewDuration != null ? viewDuration : 0)
                .setViewCount(1)
                .setLastViewedAt(now)
                .setCreatedAt(now);
        try {
            ItemDTO item = itemClient.queryItemById(itemId);
            if (item != null) {
                // shopId 取商品创建人（商家用户ID）；category 取商品类目名称
                history.setShopId(item.getCreater());
                history.setCategory(item.getCategory());
            }
        } catch (Exception e) {
            // 拉取商品信息失败时 shopId/category 允许为 null，不阻塞记录
            log.warn("记录浏览时拉取商品信息失败，itemId={}, err={}", itemId, e.getMessage());
        }
        this.save(history);
    }

    @Override
    public void deleteById(Long id) {
        Long userId = UserContext.getUser();
        // 校验所属用户后删除
        this.remove(new LambdaQueryWrapper<UserBrowseHistory>()
                .eq(UserBrowseHistory::getId, id)
                .eq(UserBrowseHistory::getUserId, userId));
    }

    @Override
    public void deleteBatch(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return;
        }
        Long userId = UserContext.getUser();
        // 校验所属用户后批量删除
        this.remove(new LambdaQueryWrapper<UserBrowseHistory>()
                .in(UserBrowseHistory::getId, ids)
                .eq(UserBrowseHistory::getUserId, userId));
    }

    @Override
    public void clearAll() {
        Long userId = UserContext.getUser();
        this.remove(new LambdaQueryWrapper<UserBrowseHistory>()
                .eq(UserBrowseHistory::getUserId, userId));
    }

    /**
     * 批量拉取商品信息，拉取失败返回空 Map（不阻塞查询）
     */
    private Map<Long, ItemDTO> fetchItems(Collection<Long> itemIds) {
        if (itemIds == null || itemIds.isEmpty()) {
            return Collections.emptyMap();
        }
        try {
            List<ItemDTO> items = itemClient.queryItemByIds(itemIds);
            if (items == null || items.isEmpty()) {
                return Collections.emptyMap();
            }
            return items.stream().filter(Objects::nonNull).collect(Collectors.toMap(ItemDTO::getId, i -> i, (a, b) -> a));
        } catch (Exception e) {
            log.warn("批量拉取商品信息失败，itemIds={}, err={}", itemIds, e.getMessage());
            return Collections.emptyMap();
        }
    }

    /**
     * 将浏览记录 PO 转为展示 VO，并填充商品信息
     */
    private UserBrowseHistoryVO toVO(UserBrowseHistory history, Map<Long, ItemDTO> itemMap) {
        UserBrowseHistoryVO vo = new UserBrowseHistoryVO();
        vo.setId(history.getId());
        vo.setItemId(history.getItemId());
        vo.setShopId(history.getShopId());
        vo.setCategory(history.getCategory());
        vo.setViewCount(history.getViewCount());
        vo.setViewSource(history.getViewSource());
        vo.setLastViewedAt(history.getLastViewedAt());
        vo.setCreatedAt(history.getCreatedAt());
        // 填充商品展示信息
        ItemDTO item = itemMap.get(history.getItemId());
        if (item != null) {
            vo.setItemName(item.getName());
            vo.setItemImage(item.getImage());
            vo.setItemPrice(item.getPrice());
            // shopId 优先用记录里的，没有则用商品创建人
            if (vo.getShopId() == null) {
                vo.setShopId(item.getCreater());
            }
        }
        return vo;
    }
}
