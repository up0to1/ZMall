package com.hmall.cart.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.hmall.cart.domain.po.Cart;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

/**
 * <p>
 * 订单详情表 Mapper 接口
 * </p>
 *
 * @author 虎哥
 * @since 2023-05-05
 */
public interface CartMapper extends BaseMapper<Cart> {

    /**
     * 按 itemId+userId 累加数量（兼容旧调用，skuId 为空时匹配 sku_id IS NULL 的记录）
     */
    @Update("UPDATE cart SET num = num + 1 WHERE user_id = #{userId} AND item_id = #{itemId} AND (sku_id <=> #{skuId})")
    void updateNum(@Param("itemId") Long itemId, @Param("skuId") Long skuId, @Param("userId") Long userId);
}
