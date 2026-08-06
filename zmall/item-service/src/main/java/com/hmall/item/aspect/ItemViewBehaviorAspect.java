package com.hmall.item.aspect;

import cn.hutool.json.JSONUtil;
import com.hmall.api.client.UserClient;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.UserBehaviorMessage;
import com.hmall.common.constants.MqConstants;
import com.hmall.common.utils.RabbitMqHelper;
import com.hmall.common.utils.UserContext;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 商品浏览行为埋点切面（P0-3 修复）
 *
 * <p>问题背景：{@link com.hmall.item.controller.ItemController#queryItemById} 上标注了
 * {@link com.hmall.common.hotkey.HotKeyCache}（@Around 切面），缓存命中时原方法体不执行，
 * 导致 ITEM_VIEW 埋点对热门商品完全丢失。
 *
 * <p>修复方案：本切面包裹 @HotKeyCache，在 pjp.proceed() 之后执行埋点。
 * 通过 {@code @Order(0)} 确保优先级高于 HotKeyCacheAspect（默认最低优先级），
 * 这样本切面位于外层：proceed() 会先经过 HotKeyCache 再到原方法，无论缓存命中与否，
 * proceed() 返回后都会执行埋点逻辑。
 *
 * <p>容错策略：埋点失败不阻塞主流程（try-catch 包裹）；未登录用户（userId 为 null）跳过埋点。
 */
@Slf4j
@Aspect
@Component
@Order(0)
@RequiredArgsConstructor
public class ItemViewBehaviorAspect {

    private final RabbitMqHelper rabbitMqHelper;
    private final UserClient userClient;

    /**
     * 拦截 ItemController.queryItemById 方法，在返回 ItemDTO 后发送 ITEM_VIEW 行为事件。
     * <p>无论 @HotKeyCache 缓存是否命中，proceed() 都会返回 ItemDTO（缓存命中返回反序列化对象，
     * 未命中执行原方法后缓存并返回），因此埋点都会执行。
     */
    @Around("execution(* com.hmall.item.controller.ItemController.queryItemById(..))")
    public Object aroundQueryItemById(ProceedingJoinPoint pjp) throws Throwable {
        // 先执行目标方法（含 @HotKeyCache 切面），获取返回值
        Object result = pjp.proceed();
        // 埋点逻辑（失败不阻塞主流程）
        try {
            if (result instanceof ItemDTO) {
                sendItemViewBehavior((ItemDTO) result);
            }
        } catch (Exception e) {
            log.error("ITEM_VIEW 埋点执行失败", e);
        }
        return result;
    }

    /**
     * 发送 ITEM_VIEW 用户行为事件
     * <p>未登录用户（userId 为 null）跳过埋点；查询用户性别失败时 userGender 传 null 兜底。
     */
    private void sendItemViewBehavior(ItemDTO dto) {
        Long currentUserId = UserContext.getUser();
        // 未登录用户跳过埋点（userId 为 null）
        if (currentUserId == null) {
            return;
        }
        // 查询用户性别（失败时 userGender 传 null 兜底，不阻塞主流程）
        String userGender = null;
        try {
            userGender = userClient.queryUserGender(currentUserId);
        } catch (Exception e) {
            log.warn("查询用户性别失败，userGender 传 null 兜底: userId={}", currentUserId, e);
        }
        // 解析 styleTags（JSON 字符串转 List）
        List<String> styleTags = null;
        if (dto.getStyleTags() != null) {
            try {
                styleTags = JSONUtil.parseArray(dto.getStyleTags()).toList(String.class);
            } catch (Exception ignore) {
                styleTags = null;
            }
        }
        // 注意：ItemDTO 无 shopId 字段，使用 creater（商家ID）作为 shopId
        UserBehaviorMessage msg = new UserBehaviorMessage(
                currentUserId,
                dto.getId(),
                dto.getCreater(),
                dto.getCategory(),
                dto.getName(),
                dto.getColor(),
                dto.getSeason(),
                dto.getPrice() != null ? dto.getPrice().doubleValue() : null,
                MqConstants.BEHAVIOR_TYPE_ITEM_VIEW,
                LocalDateTime.now().toString(),
                dto.getImage(),
                styleTags,
                dto.getTargetGender(),
                userGender
        );
        rabbitMqHelper.sendMessage(
                MqConstants.USER_BEHAVIOR_EXCHANGE,
                MqConstants.USER_BEHAVIOR_KEY_PREFIX + MqConstants.BEHAVIOR_TYPE_ITEM_VIEW,
                msg
        );
        log.info("已发送用户行为事件: type={}, userId={}, itemId={}",
                MqConstants.BEHAVIOR_TYPE_ITEM_VIEW, currentUserId, dto.getId());
    }
}
