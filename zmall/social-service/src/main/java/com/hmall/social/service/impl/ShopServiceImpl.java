package com.hmall.social.service.impl;

import cn.hutool.core.bean.BeanUtil;
import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmall.common.domain.PageDTO;
import com.hmall.api.dto.FansStatsDTO;
import com.hmall.api.vo.FansVO;
import com.hmall.api.vo.FeedVO;
import com.hmall.common.config.RedisConstants;
import com.hmall.common.config.RedisIdWorker;
import com.hmall.common.constants.MqConstants;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.RabbitMqHelper;
import com.hmall.common.utils.UserContext;
import com.hmall.common.exception.BadRequestException;
import com.hmall.api.dto.ShopFeedDTO;
import com.hmall.social.domain.dto.ShopProfileDTO;
import com.hmall.social.domain.dto.ShopFeedMessage;
import com.hmall.social.domain.dto.FeedScrollDTO;
import com.hmall.social.domain.po.ShopFeed;
import com.hmall.social.domain.po.ShopFollow;
import com.hmall.social.domain.po.Shop;
import com.hmall.social.mapper.ShopFeedMapper;
import com.hmall.social.mapper.ShopFollowMapper;
import com.hmall.social.service.IShopService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.Collections;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class ShopServiceImpl implements IShopService {

    private final ShopFollowMapper shopFollowMapper;
    private final ShopFeedMapper shopFeedMapper;
    private final com.hmall.social.mapper.ShopMapper shopMapper;
    private final RedisIdWorker redisIdWorker;
    private final StringRedisTemplate stringRedisTemplate;
    private final RabbitMqHelper rabbitMqHelper;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void followShop(Long shopId, Long userId) {
        Long count = Long.valueOf(shopFollowMapper.selectCount(
                new LambdaQueryWrapper<ShopFollow>()
                        .eq(ShopFollow::getUserId, userId)
                        .eq(ShopFollow::getShopId, shopId)));
        if (count != null && count > 0) {
            return;
        }
        ShopFollow follow = new ShopFollow();
        follow.setUserId(userId);
        follow.setShopId(shopId);
        shopFollowMapper.insert(follow);
        String key = RedisConstants.FEED_KEY + "follow:shops:" + userId;
        stringRedisTemplate.opsForSet().add(key, shopId.toString());
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void unfollowShop(Long shopId, Long userId) {
        shopFollowMapper.delete(
                new LambdaQueryWrapper<ShopFollow>()
                        .eq(ShopFollow::getUserId, userId)
                        .eq(ShopFollow::getShopId, shopId));
        String key = RedisConstants.FEED_KEY + "follow:shops:" + userId;
        stringRedisTemplate.opsForSet().remove(key, shopId.toString());
    }

    @Override
    public boolean isFollowed(Long shopId, Long userId) {
        Long count = Long.valueOf(shopFollowMapper.selectCount(
                new LambdaQueryWrapper<ShopFollow>()
                        .eq(ShopFollow::getUserId, userId)
                        .eq(ShopFollow::getShopId, shopId)));
        return count != null && count > 0;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public Long publishFeed(ShopFeedDTO feedDTO) {
        Long userId = UserContext.getUser();
        // 根据当前登录用户查询对应的店铺
        Shop shop = shopMapper.selectOne(
                new LambdaQueryWrapper<Shop>().eq(Shop::getUserId, userId));
        if (shop == null) {
            throw new BadRequestException("请先创建商店信息再进行发布管理");
        }
        long feedId = redisIdWorker.nextId(RedisConstants.ID_PREFIX_FEED);
        long now = System.currentTimeMillis();
        ShopFeed feed = BeanUtils.copyBean(feedDTO, ShopFeed.class);
        feed.setId(feedId);
        feed.setShopId(shop.getId());
        feed.setUserId(userId);
        feed.setLiked(0);
        shopFeedMapper.insert(feed);
        String feedKey = RedisConstants.FEED_KEY + "shop:" + shop.getId();
        stringRedisTemplate.opsForZSet().add(feedKey, String.valueOf(feedId), (double) now);
        stringRedisTemplate.expire(feedKey, 7, TimeUnit.DAYS);
        ShopFeedMessage message = new ShopFeedMessage(feedId, shop.getId(),
                feedDTO.getContent(), now);
        rabbitMqHelper.sendMessageWithConfirm(
                MqConstants.SHOP_FEED_DIRECT_EXCHANGE,
                MqConstants.SHOP_FEED_KEY,
                message,
                3);
        log.info("商家动态发布成功，已发送异步推送消息: feedId={}, shopId={}", feedId, shop.getId());
        return feedId;
    }

    @Override
    public List<ShopFeedDTO> queryShopFeeds(Long shopId, int page, int size) {
        Page<ShopFeed> pageResult = shopFeedMapper.selectPage(
                new Page<>(page, size),
                new LambdaQueryWrapper<ShopFeed>()
                        .eq(ShopFeed::getShopId, shopId)
                        .orderByDesc(ShopFeed::getCreateTime));
        List<ShopFeed> records = pageResult.getRecords();
        if (records == null || records.isEmpty()) {
            return Collections.emptyList();
        }
        return records.stream()
                .map(f -> BeanUtils.copyBean(f, ShopFeedDTO.class))
                .collect(Collectors.toList());
    }

    @Override
    public PageDTO<FansVO> queryFansPage(int page, int size, String keyword) {
        LambdaQueryWrapper<ShopFollow> wrapper = new LambdaQueryWrapper<ShopFollow>()
                .like(StrUtil.isNotBlank(keyword), ShopFollow::getUserId, keyword)
                .orderByDesc(ShopFollow::getCreateTime);
        Page<ShopFollow> followPage = shopFollowMapper.selectPage(new Page<>(page, size), wrapper);
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

        List<FansVO> list = followPage.getRecords().stream().map(f -> {
            FansVO vo = new FansVO();
            vo.setUserId(f.getUserId());
            vo.setCreateTime(f.getCreateTime() != null ? f.getCreateTime().format(formatter) : null);
            return vo;
        }).collect(Collectors.toList());
        return PageDTO.of(followPage.getTotal(), followPage.getPages(), list);
    }

    @Override
    public FansStatsDTO getFansStats() {
        LocalDateTime todayStart = LocalDateTime.of(LocalDate.now(), LocalTime.MIN);
        LocalDateTime weekStart = LocalDateTime.of(LocalDate.now().minusDays(6), LocalTime.MIN);

        FansStatsDTO stats = new FansStatsDTO();
        stats.setTotalFans(Long.valueOf(shopFollowMapper.selectCount(null)));
        stats.setTodayNew(Long.valueOf(shopFollowMapper.selectCount(
                new LambdaQueryWrapper<ShopFollow>().ge(ShopFollow::getCreateTime, todayStart))));
        stats.setWeekNew(Long.valueOf(shopFollowMapper.selectCount(
                new LambdaQueryWrapper<ShopFollow>().ge(ShopFollow::getCreateTime, weekStart))));
        stats.setActiveFans(Long.valueOf(shopFollowMapper.selectCount(null)));
        return stats;
    }

    @Override
    @Transactional
    public void deleteFeed(Long feedId) {
        shopFeedMapper.deleteById(feedId);
        log.info("商家Feed动态已删除: feedId={}", feedId);
    }

    @Override
    public PageDTO<FeedVO> queryFeedPage(int page, int size, String keyword) {
        LambdaQueryWrapper<ShopFeed> wrapper = new LambdaQueryWrapper<ShopFeed>()
                .like(StrUtil.isNotBlank(keyword), ShopFeed::getContent, keyword)
                .orderByDesc(ShopFeed::getCreateTime);
        Page<ShopFeed> feedPage = shopFeedMapper.selectPage(new Page<>(page, size), wrapper);
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        List<FeedVO> list = feedPage.getRecords().stream().map(f -> {
            FeedVO vo = new FeedVO();
            vo.setId(f.getId());
            vo.setShopId(f.getShopId());
            vo.setUserId(f.getUserId());
            vo.setItemId(f.getItemId());
            vo.setContent(f.getContent());
            vo.setImages(f.getImages());
            vo.setLiked(f.getLiked());
            vo.setCreateTime(f.getCreateTime() != null ? f.getCreateTime().format(formatter) : null);
            return vo;
        }).collect(Collectors.toList());
        return PageDTO.of(feedPage.getTotal(), feedPage.getPages(), list);
    }

    @Override
    public ShopProfileDTO getShopInfoByUserId(Long userId) {
        // 根据商家用户ID查询店铺
        Shop shop = shopMapper.selectOne(
                new LambdaQueryWrapper<Shop>().eq(Shop::getUserId, userId));
        if (shop == null) {
            ShopProfileDTO dto = new ShopProfileDTO();
            dto.setId(userId);
            dto.setUserId(userId);
            dto.setShopName("商家" + userId);
            return dto;
        }
        ShopProfileDTO dto = new ShopProfileDTO();
        dto.setId(shop.getId());
        dto.setUserId(shop.getUserId() != null ? shop.getUserId() : shop.getId());
        dto.setShopName(shop.getShopName());
        dto.setLogo(shop.getLogo());
        dto.setDescription(shop.getDescription());
        dto.setContactPhone(shop.getContactPhone());
        dto.setAddress(shop.getAddress());
        return dto;
    }

    @Override
    public FeedScrollDTO<FeedVO> queryFollowFeed(Long userId, Double lastScore, Double firstScore, int size) {
        String inboxKey = RedisConstants.FEED_KEY + "inbox:" + userId;

        try {
            Long total = stringRedisTemplate.opsForZSet().zCard(inboxKey);
            if (total == null || total == 0) {
                // Redis收件箱为空，回退MySQL
                return queryFollowFeedFromMySQL(userId, lastScore, firstScore, size);
            }

            // 滚动分页查询
            Set<org.springframework.data.redis.core.ZSetOperations.TypedTuple<String>> tuples;
            if (lastScore != null) {
                // 下一页：查询score < lastScore的数据
                tuples = stringRedisTemplate.opsForZSet().reverseRangeByScoreWithScores(
                        inboxKey, Double.NEGATIVE_INFINITY, lastScore, 0, size);
            } else if (firstScore != null) {
                // 上一页：查询score > firstScore的数据
                tuples = stringRedisTemplate.opsForZSet().reverseRangeByScoreWithScores(
                        inboxKey, firstScore, Double.POSITIVE_INFINITY, 0, size);
            } else {
                // 首页：查询最新的数据
                tuples = stringRedisTemplate.opsForZSet().reverseRangeWithScores(inboxKey, 0, size - 1);
            }

            if (tuples == null || tuples.isEmpty()) {
                return new FeedScrollDTO<>(Collections.emptyList(), total, null, null, false, firstScore != null);
            }

            // 提取feedId和score
            java.util.List<Long> feedIds = new java.util.ArrayList<>();
            Double minScore = null;
            Double maxScore = null;
            java.util.Map<Long, Double> scoreMap = new java.util.HashMap<>();
            for (org.springframework.data.redis.core.ZSetOperations.TypedTuple<String> tuple : tuples) {
                Long feedId = Long.valueOf(tuple.getValue());
                Double score = tuple.getScore();
                feedIds.add(feedId);
                scoreMap.put(feedId, score);
                if (minScore == null || score < minScore) minScore = score;
                if (maxScore == null || score > maxScore) maxScore = score;
            }

            // 批量查MySQL获取详情
            List<ShopFeed> feeds = shopFeedMapper.selectBatchIds(feedIds);
            java.util.Map<Long, ShopFeed> feedMap = feeds.stream()
                    .collect(Collectors.toMap(ShopFeed::getId, f -> f, (a, b) -> a));

            // 清理Redis中已删除的feedId
            java.util.List<Long> staleFeedIds = feedIds.stream()
                    .filter(id -> !feedMap.containsKey(id))
                    .collect(Collectors.toList());
            if (!staleFeedIds.isEmpty()) {
                for (Long staleId : staleFeedIds) {
                    stringRedisTemplate.opsForZSet().remove(inboxKey, staleId.toString());
                }
                total -= staleFeedIds.size();
                log.info("清理Redis收件箱中已删除的feedId: userId={}, staleIds={}", userId, staleFeedIds);
            }
            // 按Redis返回的顺序排列
            List<ShopFeed> sortedFeeds = feedIds.stream()
                    .map(feedMap::get)
                    .filter(java.util.Objects::nonNull)
                    .collect(Collectors.toList());

            // 查询商家信息
            List<Long> shopIds = sortedFeeds.stream().map(ShopFeed::getShopId).distinct().collect(Collectors.toList());
            List<Shop> shops = shopMapper.selectList(
                    new LambdaQueryWrapper<Shop>().in(Shop::getId, shopIds));
            java.util.Map<Long, Shop> shopMap = shops.stream()
                    .collect(Collectors.toMap(Shop::getId, s -> s, (a, b) -> a));

            DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
            List<FeedVO> list = sortedFeeds.stream().map(f -> {
                FeedVO vo = new FeedVO();
                vo.setId(f.getId());
                vo.setShopId(f.getShopId());
                vo.setUserId(f.getUserId());
                vo.setItemId(f.getItemId());
                vo.setContent(f.getContent());
                vo.setImages(f.getImages());
                vo.setLiked(f.getLiked());
                vo.setCreateTime(f.getCreateTime() != null ? f.getCreateTime().format(formatter) : null);
                vo.setScore(scoreMap.get(f.getId()));
                Shop shop = shopMap.get(f.getShopId());
                if (shop != null) {
                    vo.setShopName(shop.getShopName());
                    vo.setShopLogo(shop.getLogo());
                }
                return vo;
            }).collect(Collectors.toList());

            // 判断是否有上一页/下一页
            boolean hasPrev = firstScore != null || (lastScore == null && total > size);
            if (lastScore != null) {
                // 检查是否有比lastScore更大的score
                Long newerCount = stringRedisTemplate.opsForZSet().count(inboxKey, lastScore, Double.POSITIVE_INFINITY);
                hasPrev = newerCount != null && newerCount > 0;
            }
            boolean hasNext = tuples.size() >= size;

            return new FeedScrollDTO<>(list, total, minScore, maxScore, hasNext, hasPrev);
        } catch (Exception e) {
            log.warn("Feed收件箱读取异常，回退MySQL: userId={}, error={}", userId, e.getMessage());
            return queryFollowFeedFromMySQL(userId, lastScore, firstScore, size);
        }
    }

    /**
     * MySQL回退查询（当Redis收件箱不可用时）
     */
    private FeedScrollDTO<FeedVO> queryFollowFeedFromMySQL(Long userId, Double lastScore, Double firstScore, int size) {
        List<ShopFollow> follows = shopFollowMapper.selectList(
                new LambdaQueryWrapper<ShopFollow>().eq(ShopFollow::getUserId, userId));
        if (follows == null || follows.isEmpty()) {
            return new FeedScrollDTO<>(Collections.emptyList(), 0L, null, null, false, false);
        }
        List<Long> shopIds = follows.stream().map(ShopFollow::getShopId).collect(Collectors.toList());
        List<Shop> shops = shopMapper.selectList(
                new LambdaQueryWrapper<Shop>().in(Shop::getId, shopIds));
        java.util.Map<Long, Shop> shopMap = shops.stream()
                .collect(Collectors.toMap(Shop::getId, s -> s, (a, b) -> a));

        LambdaQueryWrapper<ShopFeed> queryWrapper = new LambdaQueryWrapper<ShopFeed>()
                .in(ShopFeed::getShopId, shopIds)
                .orderByDesc(ShopFeed::getCreateTime);

        // 基于时间戳的滚动分页
        if (lastScore != null) {
            // 下一页：创建时间 < lastScore
            queryWrapper.lt(ShopFeed::getCreateTime, LocalDateTime.ofInstant(
                    java.time.Instant.ofEpochMilli(lastScore.longValue()),
                    java.time.ZoneId.systemDefault()));
        } else if (firstScore != null) {
            // 上一页：创建时间 > firstScore
            queryWrapper.gt(ShopFeed::getCreateTime, LocalDateTime.ofInstant(
                    java.time.Instant.ofEpochMilli(firstScore.longValue()),
                    java.time.ZoneId.systemDefault()));
        }
        queryWrapper.last("LIMIT " + (size + 1));

        List<ShopFeed> feeds = shopFeedMapper.selectList(queryWrapper);
        boolean hasNext = feeds.size() > size;
        if (hasNext) feeds = feeds.subList(0, size);

        Long totalCount = Long.valueOf(shopFeedMapper.selectCount(
                new LambdaQueryWrapper<ShopFeed>().in(ShopFeed::getShopId, shopIds)));

        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
        Double minScore = null;
        Double maxScore = null;
        List<FeedVO> list = new java.util.ArrayList<>();
        for (ShopFeed f : feeds) {
            FeedVO vo = new FeedVO();
            vo.setId(f.getId());
            vo.setShopId(f.getShopId());
            vo.setUserId(f.getUserId());
            vo.setItemId(f.getItemId());
            vo.setContent(f.getContent());
            vo.setImages(f.getImages());
            vo.setLiked(f.getLiked());
            vo.setCreateTime(f.getCreateTime() != null ? f.getCreateTime().format(formatter) : null);
            double score = f.getCreateTime() != null ?
                    f.getCreateTime().atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli() : 0.0;
            vo.setScore(score);
            if (minScore == null || score < minScore) minScore = score;
            if (maxScore == null || score > maxScore) maxScore = score;
            Shop shop = shopMap.get(f.getShopId());
            if (shop != null) {
                vo.setShopName(shop.getShopName());
                vo.setShopLogo(shop.getLogo());
            }
            list.add(vo);
        }

        boolean hasPrev = firstScore != null;
        return new FeedScrollDTO<>(list, totalCount, minScore, maxScore, hasNext, hasPrev);
    }

    @Override
    public PageDTO<ShopProfileDTO> queryFollowList(Long userId, int page, int size) {
        // 查询用户关注的商家
        Page<ShopFollow> followPage = shopFollowMapper.selectPage(
                new Page<>(page, size),
                new LambdaQueryWrapper<ShopFollow>()
                        .eq(ShopFollow::getUserId, userId)
                        .orderByDesc(ShopFollow::getCreateTime));
        if (followPage.getRecords() == null || followPage.getRecords().isEmpty()) {
            return PageDTO.of(0L, 1, Collections.emptyList());
        }
        List<Long> shopIds = followPage.getRecords().stream()
                .map(ShopFollow::getShopId).collect(Collectors.toList());
        List<Shop> shops = shopMapper.selectList(
                new LambdaQueryWrapper<Shop>().in(Shop::getId, shopIds));
        java.util.Map<Long, Shop> shopMap = shops.stream()
                .collect(Collectors.toMap(Shop::getId, s -> s, (a, b) -> a));
        List<ShopProfileDTO> list = shopIds.stream()
                .map(shopMap::get)
                .filter(java.util.Objects::nonNull)
                .map(shop -> {
                    ShopProfileDTO dto = new ShopProfileDTO();
                    dto.setId(shop.getId());
                    dto.setUserId(shop.getUserId());
                    dto.setShopName(shop.getShopName());
                    dto.setLogo(shop.getLogo());
                    dto.setDescription(shop.getDescription());
                    return dto;
                }).collect(Collectors.toList());
        return PageDTO.of(followPage.getTotal(), followPage.getPages(), list);
    }
}