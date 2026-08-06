package com.hmall.social.service;

import com.hmall.social.domain.dto.ShopProfileDTO;

public interface IShopProfileService {

    ShopProfileDTO getProfile();

    void updateProfile(ShopProfileDTO dto);

    /**
     * 根据商家用户ID查询店铺名（供其他服务调用，如 AI 模特图水印）
     * 2026-07-19 新增
     */
    String getShopNameByUserId(Long userId);
}
