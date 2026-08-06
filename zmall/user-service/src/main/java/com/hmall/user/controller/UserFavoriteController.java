package com.hmall.user.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.hmall.common.utils.UserContext;
import com.hmall.user.domain.po.UserFavorite;
import com.hmall.user.mapper.UserFavoriteMapper;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 用户商品收藏
 * <p>收藏/取消收藏/查询收藏列表/检查是否已收藏
 */
@Api(tags = "用户商品收藏接口")
@RestController
@RequestMapping("/favorites")
@RequiredArgsConstructor
public class UserFavoriteController {

    private final UserFavoriteMapper userFavoriteMapper;

    @ApiOperation("收藏商品（uk_user_item 唯一约束防重复）")
    @PostMapping("/{itemId}")
    public void addFavorite(@PathVariable("itemId") Long itemId) {
        Long userId = UserContext.getUser();
        // 检查是否已收藏（唯一约束兜底，这里先查避免触发异常）
        Integer count = userFavoriteMapper.selectCount(
                new LambdaQueryWrapper<UserFavorite>()
                        .eq(UserFavorite::getUserId, userId)
                        .eq(UserFavorite::getItemId, itemId));
        if (count != null && count > 0) {
            return; // 已收藏，幂等返回
        }
        UserFavorite fav = new UserFavorite()
                .setUserId(userId)
                .setItemId(itemId);
        userFavoriteMapper.insert(fav);
    }

    @ApiOperation("取消收藏")
    @DeleteMapping("/{itemId}")
    public void removeFavorite(@PathVariable("itemId") Long itemId) {
        Long userId = UserContext.getUser();
        userFavoriteMapper.delete(
                new LambdaQueryWrapper<UserFavorite>()
                        .eq(UserFavorite::getUserId, userId)
                        .eq(UserFavorite::getItemId, itemId));
    }

    @ApiOperation("查询我的收藏列表（返回商品ID列表，前端自行调 item-service 获取商品详情）")
    @GetMapping
    public List<Long> listMyFavorites() {
        Long userId = UserContext.getUser();
        List<UserFavorite> list = userFavoriteMapper.selectList(
                new LambdaQueryWrapper<UserFavorite>()
                        .eq(UserFavorite::getUserId, userId)
                        .orderByDesc(UserFavorite::getCreateTime));
        return list.stream().map(UserFavorite::getItemId).collect(Collectors.toList());
    }

    @ApiOperation("检查是否已收藏单个商品")
    @GetMapping("/{itemId}/check")
    public Map<String, Boolean> checkFavorite(@PathVariable("itemId") Long itemId) {
        Long userId = UserContext.getUser();
        Integer count = userFavoriteMapper.selectCount(
                new LambdaQueryWrapper<UserFavorite>()
                        .eq(UserFavorite::getUserId, userId)
                        .eq(UserFavorite::getItemId, itemId));
        Map<String, Boolean> result = new HashMap<>();
        result.put("isFavorite", count != null && count > 0);
        return result;
    }

    @ApiOperation("批量检查是否已收藏（商品详情页/列表页用）")
    @GetMapping("/batch-check")
    public Map<Long, Boolean> batchCheck(@RequestParam("itemIds") List<Long> itemIds) {
        Long userId = UserContext.getUser();
        List<UserFavorite> list = userFavoriteMapper.selectList(
                new LambdaQueryWrapper<UserFavorite>()
                        .eq(UserFavorite::getUserId, userId)
                        .in(UserFavorite::getItemId, itemIds));
        Map<Long, Boolean> result = new HashMap<>();
        for (Long id : itemIds) {
            result.put(id, false);
        }
        for (UserFavorite fav : list) {
            result.put(fav.getItemId(), true);
        }
        return result;
    }
}
