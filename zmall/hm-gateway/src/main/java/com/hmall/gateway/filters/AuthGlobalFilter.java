package com.hmall.gateway.filters;

import com.hmall.gateway.config.AuthProperties;
import com.hmall.common.config.JwtTool;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.util.AntPathMatcher;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.List;

@Slf4j
@Component
@RequiredArgsConstructor
public class AuthGlobalFilter implements GlobalFilter, Ordered {

    private final AuthProperties authProperties;
    private final JwtTool jwtTool;
    private final AntPathMatcher antPathMatcher = new AntPathMatcher();

    /** 需要商家角色的路径模式
     * <p>注意：/shop/feed/{shopId} 是前台公开接口（用户查看商家推送），不能限制为商家。
     * 商家后台路径用精确匹配：/shop/fans/page, /shop/fans/stats, /shop/feed/page, /shop/feed/upload。
     * POST /shop/feed 和 DELETE /shop/feed/{feedId} 在 Service 层做角色与所有权校验。 */
    private static final List<String> MERCHANT_PATH_PATTERNS = List.of(
            "/merchant/**",
            "/orders/merchant/**",
            "/items/admin/**",
            "/coupons/admin/**",
            "/seckill/admin/**",
            "/shop/fans/page",
            "/shop/fans/stats",
            "/shop/feed/page",
            "/shop/feed/upload",
            "/users/verify"
    );
    /** 前台公开访问路径（硬编码，防止Nacos配置覆盖导致鉴权失败） */
    private static final List<String> PUBLIC_PATH_PATTERNS = List.of(
            "/seckill/items",
            "/seckill/items/**",
            "/seckill/coupons",
            "/seckill/coupons/**",
            "/coupons/available",
            "/coupons/item/**"
    );
    /** 服务间内部接口路径（禁止外部访问，仅允许来自微服务的调用） */
    private static final List<String> INTERNAL_PATH_PATTERNS = List.of(
            "/addresses/internal/**",
            "/users/internal/**",
            "/items/internal/**",
            "/orders/internal/**",
            "/coupons/internal/**"
    );
    /** 商家管理员角色值 */
    private static final int ROLE_MERCHANT = 2;

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {

        ServerHttpRequest request = exchange.getRequest();
        String path = request.getPath().toString();
        log.info("【网关鉴权】请求路径: {}", path);

        // 服务间内部接口：网关层直接拒绝，避免外部越权访问
        // 内部接口仅供微服务间通过 FeignClient 调用（不经网关）
        boolean isInternalPath = INTERNAL_PATH_PATTERNS.stream()
                .anyMatch(pattern -> antPathMatcher.match(pattern, path));
        if (isInternalPath) {
            log.warn("【网关鉴权】拒绝外部访问内部接口: {}", path);
            ServerHttpResponse response = exchange.getResponse();
            response.setStatusCode(HttpStatus.NOT_FOUND);
            return response.setComplete();
        }

        // 后台管理路径即使匹配了excludePaths也需要鉴权
        boolean isAdminPath = MERCHANT_PATH_PATTERNS.stream()
                .anyMatch(pattern -> antPathMatcher.match(pattern, path));

        boolean excluded = isExclude(path);
        if (!isAdminPath && excluded) {
            log.info("【网关鉴权】路径已放行(公开路径): {}", path);
            return chain.filter(exchange);
        }

        String token = null;
        List<String> headers = request.getHeaders().get("authorization");

        if (headers != null && !headers.isEmpty()) {
            token = headers.get(0);
        }

        // WebSocket 升级请求：浏览器原生 WS API 无法设置自定义 header，
        // 前端通过 ?token=xxx 传递，此处从 query param 提取并校验
        if (token == null) {
            String upgrade = request.getHeaders().getFirst("upgrade");
            if ("websocket".equalsIgnoreCase(upgrade)) {
                token = request.getQueryParams().getFirst("token");
                if (token != null && token.startsWith("Bearer ")) {
                    token = token.substring(7);
                }
            }
        }

        // 去掉"Bearer "前缀（兼容有/无前缀的token格式）
        if (token != null && token.startsWith("Bearer ")) {
            token = token.substring(7);
        }

        Long userId;
        Integer role;
        try {
            userId = jwtTool.parseToken(token);
            role = jwtTool.parseRole(token);
        } catch (Exception e) {
            log.warn("【网关鉴权】token验证失败, path={}, token={}, error={}", path,
                    token != null ? token.substring(0, Math.min(20, token.length())) + "..." : "null", e.getMessage());
            ServerHttpResponse response = exchange.getResponse();
            response.setStatusCode(HttpStatus.UNAUTHORIZED);
            return response.setComplete();
        }

        // 商家后台路径校验角色
        if (isAdminPath) {
            if (role == null || role != ROLE_MERCHANT) {
                ServerHttpResponse response = exchange.getResponse();
                response.setStatusCode(HttpStatus.FORBIDDEN);
                return response.setComplete();
            }
        }

        String userInfo = userId.toString();
        Integer finalRole = role;
        ServerWebExchange swe = exchange.mutate()
                .request(builder -> {
                    builder.header("user-info", userInfo);
                    if (finalRole != null) {
                        builder.header("user-role", finalRole.toString());
                    }
                })
                .build();

        return chain.filter(swe);
    }

    private boolean isExclude(String path) {
        // 先检查硬编码的公开路径
        for (String pathPattern : PUBLIC_PATH_PATTERNS) {
            if (antPathMatcher.match(pathPattern, path)) {
                return true;
            }
        }
        // 再检查配置文件中的排除路径
        List<String> excludePaths = authProperties.getExcludePaths();
        if (excludePaths != null) {
            for (String pathPattern : excludePaths) {
                if (antPathMatcher.match(pathPattern, path)) {
                    return true;
                }
            }
        }
        return false;
    }

    @Override
    public int getOrder() {
        return 0;
    }
}