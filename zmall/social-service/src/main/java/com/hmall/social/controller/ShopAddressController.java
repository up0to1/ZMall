package com.hmall.social.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.hmall.common.utils.UserContext;
import com.hmall.social.domain.dto.ShopAddressDTO;
import com.hmall.social.domain.po.Shop;
import com.hmall.social.domain.po.ShopAddress;
import com.hmall.social.mapper.ShopAddressMapper;
import com.hmall.social.mapper.ShopMapper;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.stream.Collectors;

/**
 * 商家发货地址管理（后台）
 * <p>每个商家可维护多个发货地址，仅一个 is_default=1 为当前发货地址。
 * <p>新增/设置默认时自动取消其他默认，保证唯一性。
 */
@Api(tags = "商家发货地址管理接口")
@RestController
@RequestMapping("/merchant/addresses")
@RequiredArgsConstructor
public class ShopAddressController {

    private final ShopAddressMapper shopAddressMapper;

    private final ShopMapper shopMapper;

    @ApiOperation("查询当前商家所有发货地址")
    @GetMapping
    public List<ShopAddressDTO> listMyAddresses() {
        Long userId = UserContext.getUser();
        List<ShopAddress> list = shopAddressMapper.selectList(
                new LambdaQueryWrapper<ShopAddress>()
                        .eq(ShopAddress::getUserId, userId)
                        .orderByDesc(ShopAddress::getIsDefault)
                        .orderByDesc(ShopAddress::getUpdateTime));
        return list.stream().map(this::toDTO).collect(Collectors.toList());
    }

    @ApiOperation("新增发货地址")
    @PostMapping
    public void addAddress(@RequestBody ShopAddressDTO dto) {
        Long userId = UserContext.getUser();
        // 若设为当前发货地址，先取消其他默认
        if (dto.getIsDefault() != null && dto.getIsDefault() == 1) {
            clearDefault(userId);
        }
        ShopAddress addr = toEntity(dto);
        addr.setUserId(userId);
        addr.setShopId(resolveShopId(userId));
        if (addr.getIsDefault() == null) {
            addr.setIsDefault(0);
        }
        shopAddressMapper.insert(addr);
    }

    @ApiOperation("修改发货地址")
    @PutMapping("/{id}")
    public void updateAddress(@PathVariable("id") Long id, @RequestBody ShopAddressDTO dto) {
        Long userId = UserContext.getUser();
        ShopAddress existing = shopAddressMapper.selectById(id);
        if (existing == null || !userId.equals(existing.getUserId())) {
            throw new IllegalArgumentException("地址不存在或无权操作");
        }
        // 若设为当前发货地址，先取消其他默认
        if (dto.getIsDefault() != null && dto.getIsDefault() == 1) {
            clearDefault(userId);
        }
        ShopAddress addr = toEntity(dto);
        addr.setId(id);
        shopAddressMapper.updateById(addr);
    }

    @ApiOperation("删除发货地址")
    @DeleteMapping("/{id}")
    public void deleteAddress(@PathVariable("id") Long id) {
        Long userId = UserContext.getUser();
        ShopAddress existing = shopAddressMapper.selectById(id);
        if (existing == null || !userId.equals(existing.getUserId())) {
            throw new IllegalArgumentException("地址不存在或无权操作");
        }
        shopAddressMapper.deleteById(id);
    }

    @ApiOperation("设为当前发货地址")
    @PutMapping("/{id}/default")
    public void setDefault(@PathVariable("id") Long id) {
        Long userId = UserContext.getUser();
        ShopAddress existing = shopAddressMapper.selectById(id);
        if (existing == null || !userId.equals(existing.getUserId())) {
            throw new IllegalArgumentException("地址不存在或无权操作");
        }
        // 先取消所有默认，再设置当前
        clearDefault(userId);
        ShopAddress addr = new ShopAddress();
        addr.setId(id);
        addr.setIsDefault(1);
        shopAddressMapper.updateById(addr);
    }

    // ===== 内部方法 =====

    /** 取消当前商家所有发货地址的默认状态 */
    private void clearDefault(Long userId) {
        shopAddressMapper.update(null,
                new LambdaUpdateWrapper<ShopAddress>()
                        .eq(ShopAddress::getUserId, userId)
                        .set(ShopAddress::getIsDefault, 0));
    }

    /** 根据用户ID查询商家ID（shop.id = userId），若店铺不存在返回 userId 作为兜底 */
    private Long resolveShopId(Long userId) {
        Shop shop = shopMapper.selectById(userId);
        return shop != null ? shop.getId() : userId;
    }

    private ShopAddressDTO toDTO(ShopAddress addr) {
        ShopAddressDTO dto = new ShopAddressDTO();
        dto.setId(addr.getId());
        dto.setProvince(addr.getProvince());
        dto.setCity(addr.getCity());
        dto.setTown(addr.getTown());
        dto.setStreet(addr.getStreet());
        dto.setContact(addr.getContact());
        dto.setMobile(addr.getMobile());
        dto.setIsDefault(addr.getIsDefault());
        dto.setNotes(addr.getNotes());
        return dto;
    }

    private ShopAddress toEntity(ShopAddressDTO dto) {
        ShopAddress addr = new ShopAddress();
        addr.setProvince(dto.getProvince());
        addr.setCity(dto.getCity());
        addr.setTown(dto.getTown());
        addr.setStreet(dto.getStreet());
        addr.setContact(dto.getContact());
        addr.setMobile(dto.getMobile());
        addr.setIsDefault(dto.getIsDefault());
        addr.setNotes(dto.getNotes());
        return addr;
    }
}
