package com.hmall.cart.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmall.cart.domain.dto.CartFormDTO;
import com.hmall.cart.domain.po.Cart;
import com.hmall.cart.domain.vo.CartVO;

import java.util.Collection;
import java.util.List;

/**
 * <p>
 * 订单详情表 服务类
 * </p>
 *
 * @author 虎哥
 * @since 2023-05-05
 */
public interface ICartService extends IService<Cart> {

    void addItem2Cart(CartFormDTO cartFormDTO);

    /**
     * 套装批量加购（AI 随心搭推荐后一键加购多件商品）
     * 已存在的商品数量 +1，不存在的商品新增条目
     *
     * @param itemIds  商品ID列表（按搭配顺序）
     * @param bundleId 套装标识（P1-11修复：写入 cart.bundle_id 用于看板统计套装加购转化率）；
     *                 为空表示普通加购（非套装），不影响现有逻辑
     */
    void batchAdd2Cart(List<Long> itemIds, String bundleId);

    List<CartVO> queryMyCarts();

    void removeByItemIds(Collection<Long> itemIds);

    void removeByItemIds(Long userId, Collection<Long> itemIds);

    /**
     * 查询指定用户购物车所有 item_id 去重列表
     * 用于 US-AT-17 排除已在购物车中的商品
     */
    List<Long> queryMyCartItemIds(Long userId);
}
