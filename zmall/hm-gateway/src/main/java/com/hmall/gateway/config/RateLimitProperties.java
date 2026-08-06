package com.hmall.gateway.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.List;

/**
 * 限流配置
 *
 * 配置示例（application.yml）：
 * <pre>
 * hm:
 *   ratelimit:
 *     enabled: true
 *     rules:
 *       - path-pattern: /api/v1/outfit/**
 *         limit: 10
 *         window-seconds: 3600
 *       - path-pattern: /api/v1/model/**
 *         limit: 10
 *         window-seconds: 3600
 * </pre>
 *
 * 维度：按 userId 限流（从 user-info 请求头获取，由 AuthGlobalFilter 写入）
 * 算法：Redis 滑动窗口（ZSET + ZREMRANGEBYSCORE）
 */
@Data
@ConfigurationProperties(prefix = "hm.ratelimit")
public class RateLimitProperties {

    /** 是否启用限流 */
    private boolean enabled = true;

    /** 限流规则列表 */
    private List<Rule> rules = new ArrayList<>();

    @Data
    public static class Rule {
        /** 路径模式（Ant 风格，如 /api/v1/outfit/**） */
        private String pathPattern;
        /** 时间窗口内允许的请求次数 */
        private int limit;
        /** 时间窗口大小（秒） */
        private int windowSeconds;
    }
}
