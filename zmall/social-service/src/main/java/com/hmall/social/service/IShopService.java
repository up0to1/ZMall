package com.hmall.social.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmall.api.dto.FansStatsDTO;
import com.hmall.api.vo.FansVO;
import com.hmall.api.vo.FeedVO;
import com.hmall.api.dto.ShopFeedDTO;
import com.hmall.social.domain.dto.ShopProfileDTO;
import com.hmall.social.domain.dto.FeedScrollDTO;
import com.hmall.common.domain.PageDTO;

import java.util.List;

public interface IShopService {

    void followShop(Long shopId, Long userId);

    void unfollowShop(Long shopId, Long userId);

    boolean isFollowed(Long shopId, Long userId);

    Long publishFeed(ShopFeedDTO feedDTO);

    List<ShopFeedDTO> queryShopFeeds(Long shopId, int page, int size);

    PageDTO<FansVO> queryFansPage(int page, int size, String keyword);

    FansStatsDTO getFansStats();

    void deleteFeed(Long feedId);

    PageDTO<FeedVO> queryFeedPage(int page, int size, String keyword);

    ShopProfileDTO getShopInfoByUserId(Long userId);

    FeedScrollDTO<FeedVO> queryFollowFeed(Long userId, Double lastScore, Double firstScore, int size);

    PageDTO<ShopProfileDTO> queryFollowList(Long userId, int page, int size);
}