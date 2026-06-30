package com.hmall.social.service;

import com.hmall.social.domain.dto.ShopProfileDTO;

public interface IShopProfileService {

    ShopProfileDTO getProfile();

    void updateProfile(ShopProfileDTO dto);
}
