package com.hmall.social.controller;

import com.hmall.common.service.FileStorageStrategy;
import com.hmall.social.domain.dto.ShopProfileDTO;
import com.hmall.social.service.IShopProfileService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@Api(tags = "商家后台-商家信息管理")
@RestController
@RequestMapping("/merchant/profile")
@RequiredArgsConstructor
public class ShopProfileController {

    private final IShopProfileService shopProfileService;
    private final FileStorageStrategy fileStorageStrategy;

    @ApiOperation("查询商家信息")
    @GetMapping
    public ShopProfileDTO getProfile() {
        return shopProfileService.getProfile();
    }

    @ApiOperation("编辑商家信息")
    @PutMapping
    public void updateProfile(@RequestBody ShopProfileDTO dto) {
        shopProfileService.updateProfile(dto);
    }

    @ApiOperation("上传商家Logo")
    @PostMapping("/upload")
    public String uploadLogo(@RequestParam("file") MultipartFile file) {
        return fileStorageStrategy.upload(file, "shop");
    }

    @ApiOperation("根据用户ID查询店铺名（内部接口，供其他服务调用）")
    @GetMapping("/shop-name")
    public String getShopNameByUserId(@RequestParam("userId") Long userId) {
        return shopProfileService.getShopNameByUserId(userId);
    }
}
