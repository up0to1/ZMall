package com.hmall.gateway.filters;

import com.hmall.gateway.config.RateLimitProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.data.domain.Range;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.util.AntPathMatcher;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;

/**
 * 全局限流过滤器
 *
 * 基于 Redis ZSET 的滑动窗口算法，按 userId 维度限流。
 * 执行顺序：在 AuthGlobalFilter 之后（order=10），确保能拿到 user-info 头。
 *
 * 算法：
 *   1. 以 ai:rate:user:{userId}:{ruleIndex} 为 ZSET key
 *   2. 每次请求 ZADD 一个 member=时间戳纳秒值，score=当前秒
 *   3. ZREMRANGEBYSCORE 移除窗口外的旧记录
 *   4. ZCARD 统计窗口内请求数，超过 limit 则拒绝
 *
 * 设计要点：
 *   - 按 userId 限流（未登录用户按 IP 限流，但不在此过滤器处理，由公开路径放行）
 *   - 滑动窗口比固定窗口更平滑，避免窗口边界突发流量
 *   - 限流维度对应后端架构方案 §7.1 "AI 接口单用户 10 次/小时"
 */
@Slf4j
@Component
@RequiredArgsConstructor
@EnableConfigurationProperties(RateLimitProperties.class)
public class RateLimitFilter implements GlobalFilter, Ordered {

    private final RateLimitProperties properties;
    private final ReactiveStringRedisTemplate redisTemplate;
    private final AntPathMatcher antPathMatcher = new AntPathMatcher();

    /** 限流 Key 前缀 */
    private static final String RATE_LIMIT_KEY_PREFIX = "ai:rate:user:";

    /** 限流后返回的错误响应体 */
    private static final String RATE_LIMIT_RESPONSE =
            "{\"code\":429,\"message\":\"请求过于频繁，请稍后再试\"}";

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        if (!properties.isEnabled() || properties.getRules().isEmpty()) {
            return chain.filter(exchange);
        }

        ServerHttpRequest request = exchange.getRequest();
        String path = request.getPath().toString();

        // 找到第一个匹配的限流规则
        RateLimitProperties.Rule matchedRule = null;
        int ruleIndex = -1;
        for (int i = 0; i < properties.getRules().size(); i++) {
            RateLimitProperties.Rule rule = properties.getRules().get(i);
            if (antPathMatcher.match(rule.getPathPattern(), path)) {
                matchedRule = rule;
                ruleIndex = i;
                break;
            }
        }
        if (matchedRule == null) {
            return chain.filter(exchange);
        }

        // 获取 userId（AuthGlobalFilter 已写入 user-info 头）
        List<String> userInfoHeaders = request.getHeaders().get("user-info");
        String userId = (userInfoHeaders != null && !userInfoHeaders.isEmpty()) ? userInfoHeaders.get(0) : null;
        if (userId == null) {
            // 未登录用户不做限流（公开路径已在 AuthGlobalFilter 放行）
            return chain.filter(exchange);
        }

        final RateLimitProperties.Rule rule = matchedRule;
        final String key = RATE_LIMIT_KEY_PREFIX + userId + ":" + ruleIndex;
        final long nowSeconds = Instant.now().getEpochSecond();
        final long windowStart = nowSeconds - rule.getWindowSeconds();
        final String member = nowSeconds + ":" + System.nanoTime();

        // 滑动窗口限流：ZADD + ZREMRANGEBYSCORE + ZCARD
        return redisTemplate.opsForZSet().add(key, member, nowSeconds)
                .then(redisTemplate.opsForZSet().removeRangeByScore(key, Range.closed(0.0, (double) windowStart)))
                .then(redisTemplate.opsForZSet().size(key))
                .flatMap(count -> {
                    if (count != null && count > rule.getLimit()) {
                        log.warn("限流触发: userId={}, path={}, count={}, limit={}",
                                userId, path, count, rule.getLimit());
                        return reject(exchange);
                    }
                    // 设置 key 过期时间（窗口的 2 倍，避免冷数据残留）
                    return redisTemplate.expire(key, java.time.Duration.ofSeconds(rule.getWindowSeconds() * 2L))
                            .then(chain.filter(exchange));
                });
    }

    private Mono<Void> reject(ServerWebExchange exchange) {
        ServerHttpResponse response = exchange.getResponse();
        response.setStatusCode(HttpStatus.TOO_MANY_REQUESTS);
        response.getHeaders().setContentType(MediaType.APPLICATION_JSON);
        return response.writeWith(Mono.just(response.bufferFactory()
                .wrap(RATE_LIMIT_RESPONSE.getBytes(StandardCharsets.UTF_8))));
    }

    @Override
    public int getOrder() {
        // 在 AuthGlobalFilter (order=0) 之后执行，确保能读到 user-info 头
        return 10;
    }
}
