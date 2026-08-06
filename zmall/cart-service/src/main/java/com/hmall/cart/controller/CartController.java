package com.hmall.cart.controller;



import com.hmall.api.dto.CartBatchDTO;
import com.hmall.cart.domain.dto.CartFormDTO;
import com.hmall.cart.domain.po.Cart;
import com.hmall.cart.domain.vo.CartVO;
import com.hmall.cart.service.ICartService;
import com.hmall.common.utils.CollUtils;
import com.hmall.common.utils.UserContext;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiImplicitParam;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import lombok.RequiredArgsConstructor;
import org.apache.ibatis.annotations.Param;
import org.springframework.web.bind.annotation.*;

import javax.validation.Valid;
import java.util.List;

@Api(tags = "购物车相关接口")
@RestController
@RequestMapping("/carts")
@RequiredArgsConstructor
public class CartController {
    private final ICartService cartService;

    @ApiOperation("添加商品到购物车")
    @PostMapping
    public void addItem2Cart(@Valid @RequestBody CartFormDTO cartFormDTO){
        cartService.addItem2Cart(cartFormDTO);
    }

    @ApiOperation("套装批量加购（AI 随心搭推荐后一键加购多件商品）")
    @PostMapping("/batch")
    public void batchAdd2Cart(@Valid @RequestBody CartBatchDTO dto){
        // P1-11修复：透传 bundleId 到 service 层，写入 cart.bundle_id 用于看板统计套装加购转化率
        cartService.batchAdd2Cart(dto.getItemIds(), dto.getBundleId());
    }

    @ApiOperation("更新购物车数据")
    @PutMapping
    public void updateCart(@RequestBody Cart cart){
        cartService.updateById(cart);
    }

    @ApiOperation("删除购物车中商品")
    @DeleteMapping("{id}")
    public void deleteCartItem(@Param ("购物车条目id")@PathVariable("id") Long id){
        cartService.removeById(id);
    }

    @ApiOperation("查询购物车列表")
    @GetMapping
    public List<CartVO> queryMyCarts(){
        return cartService.queryMyCarts();
    }

    @ApiOperation("批量删除购物车中商品")
    @ApiImplicitParam(name = "ids", value = "购物车条目id集合")
    @DeleteMapping
    public void deleteCartItemByIds(@RequestParam("ids") List<Long> ids){
        cartService.removeByItemIds(ids);
    }

    @ApiOperation("查询用户购物车所有 item_id 去重列表（用于排除已在购物车中的商品）")
    @GetMapping("/my-item-ids")
    public List<Long> queryMyCartItemIds(
            @ApiParam("用户ID（服务间调用时显式传入；用户端调用可不传，自动从 UserContext 获取）")
            @RequestParam(value = "userId", required = false) Long userId) {
        // 同时支持 UserContext 用户端调用和服务间显式 userId 调用
        Long targetUserId = userId != null ? userId : UserContext.getUser();
        if (targetUserId == null) {
            return CollUtils.emptyList();
        }
        return cartService.queryMyCartItemIds(targetUserId);
    }
}
