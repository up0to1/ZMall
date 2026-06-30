package com.hmall.social.controller;

import com.hmall.common.domain.PageDTO;
import com.hmall.api.dto.FansStatsDTO;
import com.hmall.api.vo.FansVO;
import com.hmall.api.vo.FeedVO;
import com.hmall.common.service.FileStorageStrategy;
import com.hmall.common.utils.UserContext;
import com.hmall.api.dto.ShopFeedDTO;
import com.hmall.social.domain.dto.ShopProfileDTO;
import com.hmall.social.domain.dto.FeedScrollDTO;
import com.hmall.social.service.IShopService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.util.Collections;
import java.util.List;
import java.util.Map;

@Api(tags = "商家关注与推送相关接口")
@RestController
@RequestMapping("/shop")
@RequiredArgsConstructor
public class ShopController {

    private final IShopService shopService;

    private final FileStorageStrategy fileStorageStrategy;

    @ApiOperation("关注商家")
    @PostMapping("/follow/{shopId}")
    public void followShop(@PathVariable("shopId") Long shopId) {
        Long userId = UserContext.getUser();
        shopService.followShop(shopId, userId);
    }

    @ApiOperation("取消关注商家")
    @DeleteMapping("/follow/{shopId}")
    public void unfollowShop(@PathVariable("shopId") Long shopId) {
        Long userId = UserContext.getUser();
        shopService.unfollowShop(shopId, userId);
    }

    @ApiOperation("查询是否已关注")
    @GetMapping("/follow/{shopId}")
    public Map<String, Boolean> isFollowed(@PathVariable("shopId") Long shopId) {
        Long userId = UserContext.getUser();
        boolean followed = shopService.isFollowed(shopId, userId);
        return Collections.singletonMap("followed", followed);
    }

    @ApiOperation("商家发布推送动态")
    @PostMapping("/feed")
    public Long publishFeed(@RequestBody ShopFeedDTO feedDTO) {
        return shopService.publishFeed(feedDTO);
    }

    @ApiOperation("查询商家推送动态列表")
    @GetMapping("/feed/{shopId}")
    public List<ShopFeedDTO> queryShopFeeds(
            @PathVariable("shopId") Long shopId,
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size) {
        return shopService.queryShopFeeds(shopId, page, size);
    }

    @ApiOperation("商家后台-粉丝列表")
    @GetMapping("/fans/page")
    public PageDTO<FansVO> queryFansPage(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size,
            @RequestParam(value = "keyword", required = false) String keyword) {
        return shopService.queryFansPage(page, size, keyword);
    }

    @ApiOperation("商家后台-粉丝统计")
    @GetMapping("/fans/stats")
    public FansStatsDTO getFansStats() {
        return shopService.getFansStats();
    }

    @ApiOperation("商家后台-删除Feed")
    @DeleteMapping("/feed/{feedId}")
    public void deleteFeed(@PathVariable("feedId") Long feedId) {
        shopService.deleteFeed(feedId);
    }

    @ApiOperation("商家后台-分页查询Feed")
    @GetMapping("/feed/page")
    public PageDTO<FeedVO> queryFeedPage(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size,
            @RequestParam(value = "keyword", required = false) String keyword) {
        return shopService.queryFeedPage(page, size, keyword);
    }

    @ApiOperation("前台-根据商家用户ID查询店铺信息")
    @GetMapping("/info/{userId}")
    public ShopProfileDTO getShopInfoByUserId(@PathVariable("userId") Long userId) {
        return shopService.getShopInfoByUserId(userId);
    }

    @ApiOperation("前台-查询用户关注的商家动态Feed流（滚动分页）")
    @GetMapping("/follow/feed")
    public FeedScrollDTO<FeedVO> queryFollowFeed(
            @RequestParam(value = "lastScore", required = false) Double lastScore,
            @RequestParam(value = "firstScore", required = false) Double firstScore,
            @RequestParam(value = "size", defaultValue = "10") int size) {
        Long userId = UserContext.getUser();
        return shopService.queryFollowFeed(userId, lastScore, firstScore, size);
    }

    @ApiOperation("前台-查询用户关注的商家列表")
    @GetMapping("/follow/list")
    public PageDTO<ShopProfileDTO> queryFollowList(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "12") int size) {
        Long userId = UserContext.getUser();
        return shopService.queryFollowList(userId, page, size);
    }

    @ApiOperation("文件上传（Feed图片）")
    @PostMapping("/feed/upload")
    public String uploadFeedImage(@RequestParam("file") MultipartFile file) {
        return fileStorageStrategy.upload(file, "feeds");
    }
}