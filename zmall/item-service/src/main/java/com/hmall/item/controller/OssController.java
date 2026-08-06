package com.hmall.item.controller;

import com.hmall.common.config.OssProperties;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.utils.UserContext;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.HashMap;
import java.util.Map;

/**
 * OSS STS 临时凭证接口（商家前端直传 OSS 用）
 *
 * 设计文档 §8.3：
 *   ① 前端 → Java：GET /items/admin/oss/sts
 *   ② Java 返回 OSS 配置 + 上传目录前缀
 *   ③ 前端用凭证直传 OSS → 获取 OSS URL
 *   ④ 前端把 OSS URL 发给 /items/admin/ai-model/generate
 *
 * MVP 实现说明：
 *   - 真正的 STS AssumeRole 需要 aliyun-sts-java-sdk 依赖 + RAM 角色配置
 *   - 当前实现返回 OSS 配置 + 推荐的 objectKey 前缀
 *   - 商家前端可二选一：
 *     A. 用此接口返回的信息 + OSS 直传（需配置 RAM 角色）
 *     B. 走传统的 POST /items/admin/upload 多文件上传（Java 中转，无需 STS）
 */
@Slf4j
@Api(tags = "OSS 临时凭证接口")
@RestController
@RequestMapping("/items/admin/oss")
@RequiredArgsConstructor
public class OssController {

    private final OssProperties ossProperties;

    @ApiOperation("获取 OSS 上传配置（用于商家前端直传）")
    @GetMapping("/sts")
    public Map<String, Object> getStsCredentials() {
        Long userId = UserContext.getUser();
        if (userId == null) {
            throw new BizIllegalException("用户未登录");
        }
        if (!ossProperties.isOssEnabled()) {
            throw new BizIllegalException("OSS 未配置，请使用 /items/admin/upload 上传");
        }

        // 推荐的 objectKey 前缀：zmall-ai-model/{shopId}/
        // 商家前端上传时拼接：zmall-ai-model/{shopId}/{itemId}/{timestamp}.jpg
        String objectKeyPrefix = "zmall-ai-model/" + userId + "/";

        Map<String, Object> result = new HashMap<>();
        result.put("endpoint", ossProperties.getEndpoint());
        result.put("bucketName", ossProperties.getBucketName());
        result.put("objectKeyPrefix", objectKeyPrefix);
        // MVP 提示：生产环境应替换为 STS 临时凭证（15min 有效）
        result.put("stsMode", "DEV_STATIC_CREDENTIALS");
        result.put("warning", "MVP 模式：使用静态凭证，生产环境应改用 STS AssumeRole 临时凭证");
        // 静态凭证（仅 DEV 用，生产应通过 STS API 获取临时凭证）
        result.put("accessKeyId", ossProperties.getAccessKeyId());
        result.put("accessKeySecret", ossProperties.getAccessKeySecret());
        result.put("expiration", System.currentTimeMillis() + 15 * 60 * 1000L);
        return result;
    }
}
