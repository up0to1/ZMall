package com.hmall.api.client;

import com.hmall.api.client.fallback.UserClientFallbackFactory;
import com.hmall.api.dto.AddressDTO;
import com.hmall.api.dto.DeductMoneyDTO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;

@FeignClient(contextId = "userClient", value = "user-service", fallbackFactory = UserClientFallbackFactory.class)
public interface UserClient {

    @PutMapping("/users/money/deduct")
    void deductMoney(@RequestBody DeductMoneyDTO dto);

    @PutMapping("/users/money/refund")
    void refundMoney(@RequestParam("userId") Long userId, @RequestParam("amount") Integer amount);

    /**
     * 内部接口：根据地址ID查询收货地址（服务间调用，无需登录态）
     * <p>供 trade-service 下单时查询收货地址
     */
    @GetMapping("/addresses/internal/{id}")
    AddressDTO findAddressById(@PathVariable("id") Long id);

    /**
     * 内部接口：查询用户性别（供行为埋点跨性别检测使用）
     * <p>取用户默认身体档案（user_body_profile.is_default=1）的 gender 字段；
     * 用户不存在或未填档案时返回 null。
     * <p>供 item/cart/trade 三个微服务的用户行为埋点（ITEM_VIEW/CART_ADD/ORDER_PLACE）补全 userGender 字段。
     */
    @GetMapping("/users/{id}/gender")
    String queryUserGender(@PathVariable("id") Long id);
}
