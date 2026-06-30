package com.hmall.common.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * OSS配置属性
 * 如果endpoint/accessKeyId/accessKeySecret/bucketName都配置了，则使用OSS存储
 * 如果为空，则使用本地存储
 */
@Data
@ConfigurationProperties(prefix = "hm.oss")
public class OssProperties {

    private String endpoint;
    private String accessKeyId;
    private String accessKeySecret;
    private String bucketName;

    /**
     * 判断是否启用了OSS
     */
    public boolean isOssEnabled() {
        return endpoint != null && !endpoint.isEmpty()
                && accessKeyId != null && !accessKeyId.isEmpty()
                && accessKeySecret != null && !accessKeySecret.isEmpty()
                && bucketName != null && !bucketName.isEmpty();
    }
}
