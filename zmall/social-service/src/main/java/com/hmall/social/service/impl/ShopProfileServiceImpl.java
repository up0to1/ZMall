package com.hmall.social.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.hmall.common.utils.UserContext;
import com.hmall.social.domain.dto.ShopProfileDTO;
import com.hmall.social.domain.po.Shop;
import com.hmall.social.mapper.ShopMapper;
import com.hmall.social.service.IShopProfileService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
@RequiredArgsConstructor
public class ShopProfileServiceImpl implements IShopProfileService {

    private final ShopMapper shopMapper;

    @Override
    public ShopProfileDTO getProfile() {
        Long userId = UserContext.getUser();
        // shop.id 就是商家用户ID
        Shop shop = shopMapper.selectById(userId);
        if (shop == null) {
            return new ShopProfileDTO();
        }
        ShopProfileDTO dto = new ShopProfileDTO();
        dto.setId(shop.getId());
        dto.setUserId(shop.getUserId() != null ? shop.getUserId() : shop.getId());
        dto.setShopName(shop.getShopName());
        dto.setLogo(shop.getLogo());
        dto.setDescription(shop.getDescription());
        dto.setContactPhone(shop.getContactPhone());
        dto.setAddress(shop.getAddress());
        return dto;
    }

    @Override
    @Transactional
    public void updateProfile(ShopProfileDTO dto) {
        Long userId = UserContext.getUser();
        // shop.id 就是商家用户ID
        Shop shop = shopMapper.selectById(userId);
        if (shop == null) {
            shop = new Shop();
            shop.setId(userId);
            shop.setUserId(userId);
            shop.setShopName(dto.getShopName());
            shop.setLogo(dto.getLogo());
            shop.setDescription(dto.getDescription());
            shop.setContactPhone(dto.getContactPhone());
            shop.setAddress(dto.getAddress());
            shopMapper.insert(shop);
            log.info("商家信息创建成功");
        } else {
            shop.setShopName(dto.getShopName());
            shop.setLogo(dto.getLogo());
            shop.setDescription(dto.getDescription());
            shop.setContactPhone(dto.getContactPhone());
            shop.setAddress(dto.getAddress());
            shopMapper.updateById(shop);
            log.info("商家信息更新成功");
        }
    }
}
