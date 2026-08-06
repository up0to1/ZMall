package com.hmall.common.service.impl;

import com.hmall.common.config.OssProperties;
import com.hmall.common.service.FileStorageStrategy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.util.UUID;

/**
 * 阿里云OSS文件存储实现
 * 需要引入aliyun-sdk-oss依赖
 */
@Slf4j
@RequiredArgsConstructor
public class OssFileStorage implements FileStorageStrategy {

    private final OssProperties ossProperties;

    @Override
    public String upload(MultipartFile file, String directory) {
        if (file == null || file.isEmpty()) {
            throw new RuntimeException("上传文件不能为空");
        }

        String originalFilename = file.getOriginalFilename();
        String extension = originalFilename != null && originalFilename.contains(".")
                ? originalFilename.substring(originalFilename.lastIndexOf("."))
                : "";
        String objectName = (directory != null ? directory + "/" : "") + UUID.randomUUID().toString().replace("-", "") + extension;

        try {
            // 使用反射方式调用OSS，避免硬依赖
            Class<?> ossClientBuilderClass = Class.forName("com.aliyun.oss.OSSClientBuilder");
            Object ossClientBuilder = ossClientBuilderClass.getDeclaredConstructor().newInstance();
            Object ossClient = ossClientBuilderClass
                    .getMethod("build", String.class, String.class, String.class)
                    .invoke(ossClientBuilder,
                            ossProperties.getEndpoint(),
                            ossProperties.getAccessKeyId(),
                            ossProperties.getAccessKeySecret());

            // 调用putObject
            Class<?> ossClass = Class.forName("com.aliyun.oss.OSS");
            ByteArrayInputStream inputStream = new ByteArrayInputStream(file.getBytes());
            ossClass.getMethod("putObject", String.class, String.class, java.io.InputStream.class)
                    .invoke(ossClient, ossProperties.getBucketName(), objectName, inputStream);

            // 关闭客户端
            ossClass.getMethod("shutdown").invoke(ossClient);

            String url = "https://" + ossProperties.getBucketName() + "." + ossProperties.getEndpoint() + "/" + objectName;
            log.info("文件上传成功(OSS): {}", url);
            return url;
        } catch (ClassNotFoundException e) {
            throw new RuntimeException("阿里云OSS SDK未引入，请添加aliyun-sdk-oss依赖");
        } catch (IOException e) {
            log.error("文件上传失败: {}", e.getMessage(), e);
            throw new RuntimeException("文件上传失败");
        } catch (Exception e) {
            log.error("OSS操作异常: {}", e.getMessage(), e);
            throw new RuntimeException("OSS操作异常: " + e.getMessage());
        }
    }

    @Override
    public String upload(byte[] content, String originalFilename, String contentType, String directory) {
        if (content == null || content.length == 0) {
            throw new RuntimeException("上传文件内容不能为空");
        }
        String extension = "";
        if (originalFilename != null && originalFilename.contains(".")) {
            extension = originalFilename.substring(originalFilename.lastIndexOf("."));
        } else if (contentType != null) {
            String ct = contentType.toLowerCase();
            if ("image/png".equals(ct)) {
                extension = ".png";
            } else if ("image/gif".equals(ct)) {
                extension = ".gif";
            } else if ("image/webp".equals(ct)) {
                extension = ".webp";
            } else if ("image/bmp".equals(ct)) {
                extension = ".bmp";
            } else {
                // image/jpeg、image/jpg 及其他类型默认 .jpg
                extension = ".jpg";
            }
        }
        String objectName = (directory != null ? directory + "/" : "")
                + UUID.randomUUID().toString().replace("-", "") + extension;

        try {
            Class<?> ossClientBuilderClass = Class.forName("com.aliyun.oss.OSSClientBuilder");
            Object ossClientBuilder = ossClientBuilderClass.getDeclaredConstructor().newInstance();
            Object ossClient = ossClientBuilderClass
                    .getMethod("build", String.class, String.class, String.class)
                    .invoke(ossClientBuilder,
                            ossProperties.getEndpoint(),
                            ossProperties.getAccessKeyId(),
                            ossProperties.getAccessKeySecret());

            Class<?> ossClass = Class.forName("com.aliyun.oss.OSS");
            ByteArrayInputStream inputStream = new ByteArrayInputStream(content);
            // contentType 非空时设置 ObjectMetadata
            if (contentType != null && !contentType.isBlank()) {
                Object metadata = Class.forName("com.aliyun.oss.model.ObjectMetadata")
                        .getDeclaredConstructor().newInstance();
                metadata.getClass().getMethod("setContentType", String.class).invoke(metadata, contentType);
                ossClass.getMethod("putObject", String.class, String.class,
                                java.io.InputStream.class, Class.forName("com.aliyun.oss.model.ObjectMetadata"))
                        .invoke(ossClient, ossProperties.getBucketName(), objectName, inputStream, metadata);
            } else {
                ossClass.getMethod("putObject", String.class, String.class, java.io.InputStream.class)
                        .invoke(ossClient, ossProperties.getBucketName(), objectName, inputStream);
            }

            ossClass.getMethod("shutdown").invoke(ossClient);

            String url = "https://" + ossProperties.getBucketName() + "." + ossProperties.getEndpoint() + "/" + objectName;
            log.info("文件上传成功(OSS,bytes版本): {}", url);
            return url;
        } catch (ClassNotFoundException e) {
            throw new RuntimeException("阿里云OSS SDK未引入，请添加aliyun-sdk-oss依赖");
        } catch (Exception e) {
            log.error("OSS操作异常: {}", e.getMessage(), e);
            throw new RuntimeException("OSS操作异常: " + e.getMessage());
        }
    }

    @Override
    public void delete(String filePath) {
        // OSS删除逻辑（如需要可扩展）
        log.info("OSS文件删除(暂未实现): {}", filePath);
    }

    @Override
    public boolean isOssMode() {
        return true;
    }
}
