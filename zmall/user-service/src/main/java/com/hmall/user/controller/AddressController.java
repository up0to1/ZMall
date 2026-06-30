package com.hmall.user.controller;


import com.hmall.common.exception.BadRequestException;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.CollUtils;
import com.hmall.common.utils.UserContext;
import com.hmall.user.domain.dto.AddressDTO;
import com.hmall.user.domain.po.Address;
import com.hmall.user.service.IAddressService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * <p>
 *  前端控制器
 * </p>
 *
 * @author 虎哥
 */
@RestController
@RequestMapping("/addresses")
@RequiredArgsConstructor
@Api(tags = "收货地址管理接口")
public class AddressController {

    private final IAddressService addressService;

    @ApiOperation("根据id查询地址")
    @GetMapping("{addressId}")
    public AddressDTO findAddressById(@ApiParam("地址id") @PathVariable("addressId") Long id) {
        // 1.根据id查询
        Address address = addressService.getById(id);
        // 2.判断当前用户
        Long userId = UserContext.getUser();
        if(!address.getUserId().equals(userId)){
            throw new BadRequestException("地址不属于当前登录用户");
        }
        return BeanUtils.copyBean(address, AddressDTO.class);
    }
    @ApiOperation("查询当前用户地址列表")
    @GetMapping
    public List<AddressDTO> findMyAddresses() {
        // 1.查询列表
        List<Address> list = addressService.query().eq("user_id", UserContext.getUser()).list();
        // 2.判空
        if (CollUtils.isEmpty(list)) {
            return CollUtils.emptyList();
        }
        // 3.转vo
        return BeanUtils.copyList(list, AddressDTO.class);
    }

    @ApiOperation("新增收货地址")
    @PostMapping
    public void addAddress(@RequestBody AddressDTO dto) {
        Long userId = UserContext.getUser();
        Address address = BeanUtils.copyBean(dto, Address.class);
        address.setUserId(userId);
        // 如果设置为默认地址，先取消其他默认
        if (address.getIsDefault() != null && address.getIsDefault() == 1) {
            addressService.lambdaUpdate().eq(Address::getUserId, userId)
                    .set(Address::getIsDefault, 0).update();
        }
        addressService.save(address);
    }

    @ApiOperation("修改收货地址")
    @PutMapping("/{id}")
    public void updateAddress(@PathVariable("id") Long id, @RequestBody AddressDTO dto) {
        Long userId = UserContext.getUser();
        Address existing = addressService.getById(id);
        if (!existing.getUserId().equals(userId)) {
            throw new BadRequestException("地址不属于当前登录用户");
        }
        Address address = BeanUtils.copyBean(dto, Address.class);
        address.setId(id);
        address.setUserId(userId);
        // 如果设置为默认地址，先取消其他默认
        if (address.getIsDefault() != null && address.getIsDefault() == 1) {
            addressService.lambdaUpdate().eq(Address::getUserId, userId)
                    .set(Address::getIsDefault, 0).update();
        }
        addressService.updateById(address);
    }

    @ApiOperation("删除收货地址")
    @DeleteMapping("/{id}")
    public void deleteAddress(@PathVariable("id") Long id) {
        Long userId = UserContext.getUser();
        Address existing = addressService.getById(id);
        if (!existing.getUserId().equals(userId)) {
            throw new BadRequestException("地址不属于当前登录用户");
        }
        addressService.removeById(id);
    }

    @ApiOperation("设置默认地址")
    @PutMapping("/{id}/default")
    public void setDefaultAddress(@PathVariable("id") Long id) {
        Long userId = UserContext.getUser();
        Address existing = addressService.getById(id);
        if (!existing.getUserId().equals(userId)) {
            throw new BadRequestException("地址不属于当前登录用户");
        }
        // 取消当前默认
        addressService.lambdaUpdate().eq(Address::getUserId, userId)
                .set(Address::getIsDefault, 0).update();
        // 设置新默认
        addressService.lambdaUpdate().eq(Address::getId, id)
                .set(Address::getIsDefault, 1).update();
    }
}
