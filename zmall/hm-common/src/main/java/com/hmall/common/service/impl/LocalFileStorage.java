package com.hmall.common.service.impl;

import com.hmall.common.config.UploadProperties;
import com.hmall.common.service.FileStorageStrategy;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.multipart.MultipartFile;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;

/**
 * 本地文件存储实现
 * 文件存储到本地磁盘，通过Nginx提供静态文件访问
 */
@Slf4j
@RequiredArgsConstructor
public class LocalFileStorage implements FileStorageStrategy {

    private final UploadProperties uploadProperties;

    @Override
    public String upload(MultipartFile file, String directory) {
        // 校验文件
        validateFile(file);

        // 生成文件名
        String originalFilename = file.getOriginalFilename();
        String extension = originalFilename != null && originalFilename.contains(".")
                ? originalFilename.substring(originalFilename.lastIndexOf("."))
                : "";
        String newFileName = UUID.randomUUID().toString().replace("-", "") + extension;

        // 构建存储路径
        String subPath = directory != null ? directory + "/" : "";
        String relativePath = uploadProperties.getUrlPrefix() + subPath + newFileName;

        // 物理存储
        File uploadDir = new File(uploadProperties.getBasePath(), subPath);
        if (!uploadDir.exists()) {
            uploadDir.mkdirs();
        }

        File destFile = new File(uploadDir, newFileName);
        try {
            file.transferTo(destFile.getAbsoluteFile());
            log.info("文件上传成功(本地存储): {}", relativePath);
        } catch (IOException e) {
            log.error("文件上传失败: {}", e.getMessage(), e);
            throw new RuntimeException("文件上传失败");
        }

        return relativePath;
    }

    @Override
    public String upload(byte[] content, String originalFilename, String contentType, String directory) {
        if (content == null || content.length == 0) {
            throw new RuntimeException("上传文件内容不能为空");
        }
        // 校验文件大小
        if (content.length > uploadProperties.getMaxSize()) {
            throw new RuntimeException("文件大小超过限制，最大允许" + (uploadProperties.getMaxSize() / 1024 / 1024) + "MB");
        }
        // 推断扩展名
        String extension = "";
        if (originalFilename != null && originalFilename.contains(".")) {
            extension = originalFilename.substring(originalFilename.lastIndexOf("."));
            String extNoDot = extension.substring(1).toLowerCase();
            Set<String> allowed = new HashSet<>(Arrays.asList(uploadProperties.getAllowedExtensions().split(",")));
            if (!allowed.contains(extNoDot)) {
                throw new RuntimeException("不支持的文件类型，仅允许: " + uploadProperties.getAllowedExtensions());
            }
        } else if (contentType != null) {
            // 从 contentType 推断扩展名
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
        String newFileName = UUID.randomUUID().toString().replace("-", "") + extension;
        String subPath = directory != null ? directory + "/" : "";
        String relativePath = uploadProperties.getUrlPrefix() + subPath + newFileName;

        File uploadDir = new File(uploadProperties.getBasePath(), subPath);
        if (!uploadDir.exists()) {
            uploadDir.mkdirs();
        }

        File destFile = new File(uploadDir, newFileName);
        try {
            Files.write(destFile.toPath(), content);
            log.info("文件上传成功(本地存储,bytes版本): {}", relativePath);
        } catch (IOException e) {
            log.error("文件上传失败: {}", e.getMessage(), e);
            throw new RuntimeException("文件上传失败");
        }
        return relativePath;
    }

    @Override
    public void delete(String filePath) {
        if (filePath == null || filePath.isEmpty()) {
            return;
        }
        // 从URL路径转换为物理路径
        String relativePath = filePath;
        if (filePath.startsWith(uploadProperties.getUrlPrefix())) {
            relativePath = filePath.substring(uploadProperties.getUrlPrefix().length());
        }

        File file = new File(uploadProperties.getBasePath(), relativePath);
        if (file.exists()) {
            if (file.delete()) {
                log.info("文件删除成功: {}", filePath);
            } else {
                log.warn("文件删除失败: {}", filePath);
            }
        }
    }

    @Override
    public boolean isOssMode() {
        return false;
    }

    private void validateFile(MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw new RuntimeException("上传文件不能为空");
        }

        // 校验文件大小
        if (file.getSize() > uploadProperties.getMaxSize()) {
            throw new RuntimeException("文件大小超过限制，最大允许" + (uploadProperties.getMaxSize() / 1024 / 1024) + "MB");
        }

        // 校验文件扩展名
        String originalFilename = file.getOriginalFilename();
        if (originalFilename != null && originalFilename.contains(".")) {
            String extension = originalFilename.substring(originalFilename.lastIndexOf(".") + 1).toLowerCase();
            Set<String> allowed = new HashSet<>(Arrays.asList(uploadProperties.getAllowedExtensions().split(",")));
            if (!allowed.contains(extension)) {
                throw new RuntimeException("不支持的文件类型，仅允许: " + uploadProperties.getAllowedExtensions());
            }
        }
    }
}
