package com.hmall.common.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 本地文件上传配置属性
 */
@Data
@ConfigurationProperties(prefix = "hm.upload")
public class UploadProperties {

    /**
     * 本地存储的物理路径（绝对路径）
     * 默认值指向 zmall-nginx/html/uploads 目录
     */
    private String basePath = "../zmall-nginx/html/uploads";

    /**
     * 访问路径前缀（相对URL路径）
     */
    private String urlPrefix = "/uploads/";

    /**
     * 允许的文件扩展名
     */
    private String allowedExtensions = "jpg,jpeg,png,gif,bmp,webp";

    /**
     * 最大文件大小（字节），默认5MB
     */
    private Long maxSize = 5 * 1024 * 1024L;
}
