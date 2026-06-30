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
