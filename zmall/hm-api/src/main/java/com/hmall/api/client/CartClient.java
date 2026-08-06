package com.hmall.api.client;

import com.hmall.api.client.fallback.CartClientFallbackFactory;
import com.hmall.api.dto.CartBatchDTO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import java.util.Collection;
import java.util.List;


@FeignClient(value = "cart-service", fallbackFactory = CartClientFallbackFactory.class)
public interface CartClient {

    @DeleteMapping("/carts")
    void deleteCartItemByIds(@RequestParam("ids") Collection<Long> ids);

    /**
     * 套装批量加购（AI 随心搭推荐后一键加购多件商品）
     */
    @PostMapping("/carts/batch")
    void batchAdd2Cart(@RequestBody CartBatchDTO dto);

    /**
     * 服务间调用：查询指定用户购物车所有 item_id 去重列表
     * 用于 US-AT-17 排除已在购物车中的商品
     */
    @GetMapping("/carts/my-item-ids")
    List<Long> queryMyCartItemIds(@RequestParam("userId") Long userId);
}
