package com.hmall.common.service;

import org.springframework.web.multipart.MultipartFile;

/**
 * 文件存储策略接口
 * 支持OSS和本地存储两种实现
 */
public interface FileStorageStrategy {

    /**
     * 上传文件
     *
     * @param file 上传的文件
     * @param directory 子目录（如 "items"），可为null
     * @return 文件访问路径（相对URL）
     */
    String upload(MultipartFile file, String directory);

    /**
     * 上传文件（字节数组版本，用于已处理的图片如加水印后的图片）
     *
     * <p>2026-07-19 新增：AI 模特图加水印后用 bytes 上传，无需包装回 MultipartFile。
     *
     * @param content 文件二进制内容
     * @param originalFilename 原始文件名（用于推断扩展名，如 "model.jpg"）
     * @param contentType MIME 类型（如 "image/jpeg"），可空
     * @param directory 子目录（如 "model-images"），可为null
     * @return 文件访问路径（相对URL）
     */
    String upload(byte[] content, String originalFilename, String contentType, String directory);

    /**
     * 删除文件
     *
     * @param filePath 文件访问路径
     */
    void delete(String filePath);

    /**
     * 判断当前是否为OSS模式
     */
    boolean isOssMode();
}
