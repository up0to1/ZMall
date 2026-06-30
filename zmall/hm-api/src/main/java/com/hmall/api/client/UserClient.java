package com.hmall.api.client;

import com.hmall.api.client.fallback.UserClientFallbackFactory;
import com.hmall.api.dto.DeductMoneyDTO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;

@FeignClient(value = "user-service", fallbackFactory = UserClientFallbackFactory.class)
public interface UserClient {

    @PutMapping("/users/money/deduct")
    void deductMoney(@RequestBody DeductMoneyDTO dto);

    @PutMapping("/users/money/refund")
    void refundMoney(@RequestParam("userId") Long userId, @RequestParam("amount") Integer amount);
}
