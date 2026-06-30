package com.hmall.api.client;

import com.hmall.api.client.fallback.CartClientFallbackFactory;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.RequestParam;
import java.util.Collection;


@FeignClient(value = "cart-service", fallbackFactory = CartClientFallbackFactory.class)
public interface CartClient {

    @DeleteMapping("/carts")
    void deleteCartItemByIds(@RequestParam("ids") Collection<Long> ids);
}
