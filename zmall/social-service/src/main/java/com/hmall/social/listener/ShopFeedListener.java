package com.hmall.social.listener;

import com.hmall.common.config.RedisConstants;
import com.hmall.common.constants.MqConstants;
import com.hmall.social.domain.dto.ShopFeedMessage;
import com.hmall.social.domain.po.ShopFollow;
import com.hmall.social.mapper.ShopFollowMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.amqp.rabbit.annotation.Exchange;
import org.springframework.amqp.rabbit.annotation.Queue;
import org.springframework.amqp.rabbit.annotation.QueueBinding;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.TimeUnit;

@Slf4j
@Component
@RequiredArgsConstructor
public class ShopFeedListener {

    private final ShopFollowMapper shopFollowMapper;
    private final StringRedisTemplate stringRedisTemplate;

    private static final String FEED_PUSHED_KEY_PREFIX = "feed:pushed:";
    private static final long FEED_PUSHED_TTL_HOURS = 24;

    @RabbitListener(bindings = @QueueBinding(
            value = @Queue(name = MqConstants.SHOP_FEED_QUEUE_NAME, durable = "true"),
            exchange = @Exchange(name = MqConstants.SHOP_FEED_DIRECT_EXCHANGE),
            key = MqConstants.SHOP_FEED_KEY
    ))
    public void listenShopFeed(ShopFeedMessage message) {
        log.info("收到商家动态推送消息: feedId={}, shopId={}", message.getFeedId(), message.getShopId());

        // 幂等检查：用Redis key标记该feedId已处理，防止重复消费导致TTL被刷新
        String dedupKey = FEED_PUSHED_KEY_PREFIX + message.getFeedId();
        Boolean isFirst = stringRedisTemplate.opsForValue().setIfAbsent(dedupKey, "1", FEED_PUSHED_TTL_HOURS, TimeUnit.HOURS);
        if (Boolean.FALSE.equals(isFirst)) {
            log.info("动态推送已处理，跳过重复消费: feedId={}", message.getFeedId());
            return;
        }

        List<ShopFollow> follows = shopFollowMapper.selectList(
                new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<ShopFollow>()
                        .eq(ShopFollow::getShopId, message.getShopId()));
        if (follows == null || follows.isEmpty()) {
            return;
        }
        for (ShopFollow follow : follows) {
            String feedKey = RedisConstants.FEED_KEY + "inbox:" + follow.getUserId();
            stringRedisTemplate.opsForZSet().add(feedKey,
                    message.getFeedId().toString(), message.getCreateTime());
            stringRedisTemplate.expire(feedKey, 7, TimeUnit.DAYS);
        }
        log.info("商家动态推送完成: feedId={}, shopId={}, 粉丝数={}",
                message.getFeedId(), message.getShopId(), follows.size());
    }
}
