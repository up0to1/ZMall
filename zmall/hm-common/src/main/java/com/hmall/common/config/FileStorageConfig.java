package com.hmall.common.config;

import com.hmall.common.service.FileStorageStrategy;
import com.hmall.common.service.impl.LocalFileStorage;
import com.hmall.common.service.impl.OssFileStorage;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;

/**
 * 文件存储自动配置
 * 根据配置自动选择OSS或本地存储
 */
@Slf4j
@EnableConfigurationProperties({OssProperties.class, UploadProperties.class})
public class FileStorageConfig {

    @Bean
    public FileStorageStrategy fileStorageStrategy(OssProperties ossProperties, UploadProperties uploadProperties) {
        if (ossProperties.isOssEnabled()) {
            log.info("========== 文件存储模式: 阿里云OSS ==========");
            log.info("OSS Endpoint: {}", ossProperties.getEndpoint());
            log.info("OSS Bucket: {}", ossProperties.getBucketName());
            return new OssFileStorage(ossProperties);
        } else {
            log.info("========== 文件存储模式: 本地存储 ==========");
            log.info("本地存储路径: {}", uploadProperties.getBasePath());
            log.info("访问路径前缀: {}", uploadProperties.getUrlPrefix());
            return new LocalFileStorage(uploadProperties);
        }
    }
}
