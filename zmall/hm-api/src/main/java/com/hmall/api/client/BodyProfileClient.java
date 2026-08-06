package com.hmall.api.client;

import com.hmall.api.client.fallback.BodyProfileClientFallbackFactory;
import com.hmall.api.dto.BodyProfileDTO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.List;

/**
 * 用户身体信息档案 Feign Client（服务间调用）
 *
 * <p>2026-07-27 新增：item-service 尺码推荐时调用 user-service 获取用户身体信息。
 *
 * @author hmall
 * @since 2026-07-27
 */
@FeignClient(contextId = "bodyProfileClient", value = "user-service", fallbackFactory = BodyProfileClientFallbackFactory.class)
public interface BodyProfileClient {

    /**
     * 服务间调用：查询单个身体信息档案
     */
    @GetMapping("/body-profile/{id}")
    BodyProfileDTO queryBodyProfile(@PathVariable("id") Long id);

    /**
     * 服务间调用：查询指定用户身体信息档案列表
     * IDOR 越权修复（2026-07-27）：路径迁移到 /internal/list，被网关 INTERNAL_PATH_PATTERNS 拦截外部访问
     */
    @GetMapping("/body-profile/internal/list")
    List<BodyProfileDTO> queryUserBodyProfiles(@RequestParam("userId") Long userId);
}
