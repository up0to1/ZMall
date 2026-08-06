package com.hmall.cart.service.impl;

import cn.hutool.core.util.StrUtil;
import cn.hutool.json.JSONUtil;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.api.client.ItemClient;
import com.hmall.api.client.SkuClient;
import com.hmall.api.client.UserClient;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.SkuDTO;
import com.hmall.api.dto.UserBehaviorMessage;
import com.hmall.cart.config.CartProPerties;
import com.hmall.cart.domain.dto.CartFormDTO;
import com.hmall.cart.domain.po.Cart;
import com.hmall.cart.domain.vo.CartVO;
import com.hmall.cart.mapper.CartMapper;
import com.hmall.cart.service.ICartService;
import com.hmall.common.constants.MqConstants;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.CollUtils;
import com.hmall.common.utils.RabbitMqHelper;
import com.hmall.common.utils.UserContext;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.LocalDateTime;
import java.util.Collection;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * <p>
 * 订单详情表 服务实现类
 * </p>
 *
 * @author 虎哥
 * @since 2023-05-05
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class CartServiceImpl extends ServiceImpl<CartMapper, Cart> implements ICartService {

    //private final RestTemplate restTemplate;
    //private final DiscoveryClient discoveryClient;
    private final ItemClient itemClient;
    private final SkuClient skuClient;
    private final UserClient userClient;
    private final CartProPerties cartProPerties;
    private final RabbitMqHelper rabbitMqHelper;

    @Override
    public void addItem2Cart(CartFormDTO cartFormDTO) {
        // 1.获取登录用户
        Long userId = UserContext.getUser();

        // 2.判断是否已经存在（按 skuId 维度，skuId 为空时退化为 item 维度）
        if(checkSkuExists(cartFormDTO.getItemId(), cartFormDTO.getSkuId(), userId)){
            // 2.1.存在，则更新数量
            baseMapper.updateNum(cartFormDTO.getItemId(), cartFormDTO.getSkuId(), userId);
            // P1-11修复：若本次属于套装加购（bundleId 非空），同步给已存在记录打上 bundle_id 标记，
            // 保证同一套装的多件商品在购物车中可被识别（仅 bundleId 非空时执行，普通加购不受影响）
            if (cartFormDTO.getBundleId() != null) {
                lambdaUpdate()
                        .eq(Cart::getUserId, userId)
                        .eq(Cart::getItemId, cartFormDTO.getItemId())
                        .set(Cart::getBundleId, cartFormDTO.getBundleId())
                        .update();
            }
            return;
        }
        // 2.2.不存在，判断是否超过购物车数量
        checkCartsFull(userId);

        // 3.新增购物车条目
        // 3.1.转换PO（CartFormDTO.bundleId 会按同名属性拷贝到 Cart.bundleId）
        Cart cart = BeanUtils.copyBean(cartFormDTO, Cart.class);
        // 3.2.保存当前用户
        cart.setUserId(userId);
        // 3.3.查询商品信息，补充name、price、image等快照字段
        //    （前端仅传itemId，cart表的name字段为NOT NULL，需后端填充）
        ItemDTO item = itemClient.queryItemById(cartFormDTO.getItemId());
        if (item == null) {
            throw new BizIllegalException("商品不存在");
        }
        // 3.4.按 skuId 查询 SKU，优先取 SKU 的价格/图片（多SKU场景下不同规格价格不同）
        //    skuId 为空时兜底取默认 SKU；若仍无 SKU，回退用 item 表的 price/image
        Long skuId = cartFormDTO.getSkuId();
        SkuDTO sku = null;
        if (skuId != null) {
            sku = skuClient.querySkuById(skuId);
            if (sku == null) {
                throw new BizIllegalException("SKU 不存在");
            }
        } else {
            sku = skuClient.queryDefaultSkuBySpuId(cartFormDTO.getItemId());
        }
        if (sku != null) {
            cart.setSkuId(sku.getId());
            cart.setName(StrUtil.isNotBlank(sku.getName()) ? sku.getName() : item.getName());
            cart.setPrice(sku.getPrice() != null ? sku.getPrice() : item.getPrice());
            cart.setImage(StrUtil.isNotBlank(sku.getImage()) ? sku.getImage() : item.getImage());
        } else {
            // 兜底：商品未配置 SKU，用 item 表字段
            cart.setName(item.getName());
            cart.setPrice(item.getPrice());
            cart.setImage(item.getImage());
        }
        cart.setNum(1);
        // 3.5.保存到数据库（bundleId 由 3.1 的 copyBean 写入，为空表示普通加购）
        save(cart);
        // 异步发送 CART_ADD 用户行为事件到 user.behavior.exchange（Phase 2.5 个性化推荐画像）
        // P1-7 修复：批量加购（batchAdd2Cart，@Transactional）场景下，MQ 原在事务内发送，
        // 若批量回滚后消息已发。改为：有事务时注册 afterCommit 回调，事务提交后才发；
        // 单件加购路径（无事务）直接发送（保持原行为）。
        registerCartAddBehavior(userId, cart, item);
    }

    /**
     * 发送 CART_ADD 用户行为事件（P1-7 修复）
     * <p>有 Spring 事务上下文（batchAdd2Cart 路径）时注册 afterCommit 回调，事务提交后才发 MQ，
     * 避免批量回滚后 MQ 已发无法回滚；无事务上下文（单件加购路径）时直接发送（保持原行为）。
     *
     * @param userId 当前登录用户 ID（effectively final，供 afterCommit 回调捕获）
     * @param cart   购物车条目（含 itemId 等快照）
     * @param item   商品 DTO（含 creater/category/color/styleTags/targetGender 等）
     */
    private void registerCartAddBehavior(Long userId, Cart cart, ItemDTO item) {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    doSendCartAddBehavior(userId, cart, item);
                }
            });
        } else {
            // 单件加购路径（无事务）：直接发送（保持原行为）
            doSendCartAddBehavior(userId, cart, item);
        }
    }

    /**
     * 实际发送 CART_ADD 用户行为事件
     * <p>注意：ItemDTO 无 shopId 字段，使用 creater（商家ID）作为 shopId。
     * <p>查询用户性别失败时 userGender 传 null 兜底（P1-8）。
     */
    private void doSendCartAddBehavior(Long userId, Cart cart, ItemDTO item) {
        // 注意：ItemDTO 无 shopId 字段，使用 creater（商家ID）作为 shopId
        try {
            List<String> styleTags = null;
            if (item.getStyleTags() != null) {
                try {
                    styleTags = JSONUtil.parseArray(item.getStyleTags()).toList(String.class);
                } catch (Exception ignore) {
                    styleTags = null;
                }
            }
            // 查询用户性别（失败时 userGender 传 null 兜底，P1-8）
            String userGender = null;
            try {
                userGender = userClient.queryUserGender(userId);
            } catch (Exception ex) {
                log.warn("查询用户性别失败，userGender 传 null 兜底: userId={}", userId, ex);
            }
            UserBehaviorMessage msg = new UserBehaviorMessage(
                    userId,
                    cart.getItemId(),
                    item.getCreater(),
                    item.getCategory(),
                    item.getName(),
                    item.getColor(),
                    item.getSeason(),
                    item.getPrice() != null ? item.getPrice().doubleValue() : null,
                    MqConstants.BEHAVIOR_TYPE_CART_ADD,
                    LocalDateTime.now().toString(),
                    item.getImage(),
                    styleTags,
                    item.getTargetGender(),
                    userGender
            );
            rabbitMqHelper.sendMessage(
                    MqConstants.USER_BEHAVIOR_EXCHANGE,
                    MqConstants.USER_BEHAVIOR_KEY_PREFIX + MqConstants.BEHAVIOR_TYPE_CART_ADD,
                    msg
            );
            log.info("已发送用户行为事件: type={}, userId={}, itemId={}",
                    MqConstants.BEHAVIOR_TYPE_CART_ADD, userId, cart.getItemId());
        } catch (Exception e) {
            log.error("发送 CART_ADD 用户行为事件失败: itemId={}", cart.getItemId(), e);
        }
    }

    @Override
    @Transactional
    public void batchAdd2Cart(List<Long> itemIds, String bundleId) {
        if (itemIds == null || itemIds.isEmpty()) {
            return;
        }
        // P1-11修复：将 bundleId 透传到每件商品的加购流程，写入 cart.bundle_id，
        // 用于看板统计 AI 随心搭套装加购转化率。bundleId 为空时退化为普通加购，向后兼容。
        for (Long itemId : itemIds) {
            CartFormDTO form = new CartFormDTO();
            form.setItemId(itemId);
            form.setBundleId(bundleId);
            addItem2Cart(form);
        }
    }

    @Override
    public List<CartVO> queryMyCarts() {
        // 1.查询我的购物车列表
        List<Cart> carts = lambdaQuery().eq(Cart::getUserId, UserContext.getUser()).list();
        if (CollUtils.isEmpty(carts)) {
            return CollUtils.emptyList();
        }

        // 2.转换VO
        List<CartVO> vos = BeanUtils.copyList(carts, CartVO.class);

        // 3.处理VO中的商品信息
        handleCartItems(vos);

        // 4.返回
        return vos;
    }

    private void handleCartItems(List<CartVO> vos) {
        // 1.获取商品id
        Set<Long> itemIds = vos.stream().map(CartVO::getItemId).collect(Collectors.toSet());
        // 2.查询商品
        //restTemplate--网络http通信和nacos技术--注册中心获取功能接口的url，负载均衡端口不止一个
        /*List<ServiceInstance> instances = discoveryClient.getInstances("item-service");
        if (CollUtil.isEmpty(instances)){
            return;
        }
        ServiceInstance instance = instances.get(RandomUtil.randomInt(instances.size()));

        //通过发起网络请求获取itemservice当中的获取商品信息功能
        ResponseEntity<List<ItemDTO>> response = restTemplate.exchange(
                instance.getUri()+"/items?ids={ids}",
                HttpMethod.GET,
                null,
                new ParameterizedTypeReference<List<ItemDTO>>() {
                },
                Map.of("ids", CollUtil.join(itemIds, ","))
        );
        //解析响应
        if (!response.getStatusCode().is2xxSuccessful()){
            //查询失败
            return;
        }
        List<ItemDTO> items = response.getBody();*/
        //openfeign技术化简restTemplate和nacos技术
        List<ItemDTO> items = itemClient.queryItemByIds(itemIds);
        if (CollUtils.isEmpty(items)) {
            return;
        }
        // 3.转为 id 到 item的map
        Map<Long, ItemDTO> itemMap = items.stream().collect(Collectors.toMap(ItemDTO::getId, Function.identity()));
        // 4.写入vo
        for (CartVO v : vos) {
            ItemDTO item = itemMap.get(v.getItemId());
            if (item == null) {
                continue;
            }
            v.setNewPrice(item.getPrice());
            v.setStatus(item.getStatus());
            v.setStock(item.getStock());
        }
    }

    @Override
    @Transactional
    public void removeByItemIds(Collection<Long> itemIds) {
        removeByItemIds(UserContext.getUser(), itemIds);
    }

    @Override
    @Transactional
    public void removeByItemIds(Long userId, Collection<Long> itemIds) {
        // 1.构建删除条件，userId和itemId
        QueryWrapper<Cart> queryWrapper = new QueryWrapper<Cart>();
        queryWrapper.lambda()
                .eq(Cart::getUserId, userId)
                .in(Cart::getItemId, itemIds);
        // 2.删除
        remove(queryWrapper);
    }

    @Override
    public List<Long> queryMyCartItemIds(Long userId) {
        if (userId == null) {
            return CollUtils.emptyList();
        }
        List<Cart> carts = lambdaQuery().eq(Cart::getUserId, userId).list();
        if (CollUtils.isEmpty(carts)) {
            return CollUtils.emptyList();
        }
        return carts.stream()
                .map(Cart::getItemId)
                .filter(itemId -> itemId != null)
                .distinct()
                .collect(Collectors.toList());
    }

    private void checkCartsFull(Long userId) {
        int count = lambdaQuery().eq(Cart::getUserId, userId).count();
        if (count >= cartProPerties.getMaxItems()) {
            throw new BizIllegalException(StrUtil.format("用户购物车课程不能超过{}", cartProPerties.getMaxItems()));
        }
    }

    private boolean checkItemExists(Long itemId, Long userId) {
        int count = lambdaQuery()
                .eq(Cart::getUserId, userId)
                .eq(Cart::getItemId, itemId)
                .count();
        return count > 0;
    }

    /**
     * 按 skuId 维度检查购物车是否已存在该 SKU（skuId 为空时退化为 item 维度，兼容旧逻辑）
     */
    private boolean checkSkuExists(Long itemId, Long skuId, Long userId) {
        var q = lambdaQuery()
                .eq(Cart::getUserId, userId)
                .eq(Cart::getItemId, itemId);
        if (skuId != null) {
            q.eq(Cart::getSkuId, skuId);
        } else {
            q.isNull(Cart::getSkuId);
        }
        return q.count() > 0;
    }
}
