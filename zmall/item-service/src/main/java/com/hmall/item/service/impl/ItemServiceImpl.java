package com.hmall.item.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.hmall.common.constants.MqConstants;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.RabbitMqHelper;
import com.hmall.api.constant.OutfitCategories;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.dto.ItemSyncMessage;
import com.hmall.api.dto.OrderDetailDTO;
import com.hmall.api.client.TradeClient;
import com.hmall.item.domain.po.AttributeValue;
import com.hmall.item.domain.po.Item;
import com.hmall.item.domain.po.SpuAttrValue;
import com.hmall.item.mapper.AttributeValueMapper;
import com.hmall.item.mapper.ItemMapper;
import com.hmall.item.mapper.SpuAttrValueMapper;
import com.hmall.item.service.IItemService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;
import java.time.LocalDateTime;

@Slf4j
@Service
@RequiredArgsConstructor
public class ItemServiceImpl extends ServiceImpl<ItemMapper, Item> implements IItemService {

    private final RabbitMqHelper rabbitMqHelper;
    private final SpuAttrValueMapper spuAttrValueMapper;
    private final AttributeValueMapper attributeValueMapper;
    private final TradeClient tradeClient;
    // v6 工具拓展：库存查询走 Redis 缓存（与 item-service 其他模块共享同一 Redis 实例）
    private final org.springframework.data.redis.core.StringRedisTemplate stringRedisTemplate;

    /** EAV 属性ID常量（与 hm-item.sql attribute 表定义对齐） */
    private static final Long ATTR_ID_COLOR = 1L;      // 颜色（销售属性，存文本值如 '白色'）
    private static final Long ATTR_ID_SIZE = 2L;        // 尺码（销售属性，存 JSON 数组文本如 '["M"]'）
    private static final Long ATTR_ID_MATERIAL = 3L;    // 材质（普通属性，存文本值如 '纯棉'）
    private static final Long ATTR_ID_SEASON = 4L;      // 季节（普通属性，存文本值如 'summer'）
    private static final Long ATTR_ID_STYLE = 5L;       // 风格（普通属性，存 JSON 数组文本如 '["休闲"]'）

    /** Jackson ObjectMapper 用于解析风格标签 JSON */
    private static final ObjectMapper JSON = new ObjectMapper();

    // ============================================================
    // 商品库同步 Qdrant（US-AT-13/18/20）
    // ============================================================
    // 重写 MyBatis-Plus 的 save/updateById/removeById，统一拦截所有写入路径，
    // 自动发 item.sync.exchange MQ 消息同步到 Python ai-outfit → Qdrant 向量库。
    // MQ 发送在事务提交后执行（registerSynchronization），避免事务回滚后误发 MQ。
    // MQ 发送失败仅记日志不抛异常，依赖定时任务对账兜底（与 AiTaskServiceImpl 一致）。

    @Override
    @Transactional
    public boolean save(Item item) {
        // P0 穿搭类目过滤：非穿搭类目不同步 Qdrant，但仍正常落 MySQL
        if (!OutfitCategories.isOutfitCategory(item.getCategory())) {
            log.debug("非穿搭类目，跳过 Qdrant 同步: itemId={}, category={}", item.getId(), item.getCategory());
            return super.save(item);
        }
        boolean ok = super.save(item);
        if (ok && item.getId() != null) {
            // 新增商品：所有字段都是"变更"字段
            sendItemUpsertSync(item.getId(), true, ALL_FIELDS_CHANGED);
        }
        return ok;
    }

    @Override
    @Transactional
    public boolean updateById(Item item) {
        // P0 穿搭类目过滤：先查原商品判断类目
        Item oldItem = (item.getId() != null) ? getById(item.getId()) : null;
        if (oldItem == null || !OutfitCategories.isOutfitCategory(oldItem.getCategory())) {
            // 原商品非穿搭类目（或不存在），直接更新 MySQL，不同步 Qdrant
            // 但若类目从非穿搭改为穿搭，按新增处理（发全字段变更）
            boolean ok = super.updateById(item);
            if (ok && oldItem == null) {
                return ok;
            }
            // 类目可能改为穿搭类目，再查一次
            if (ok && item.getCategory() != null
                    && OutfitCategories.isOutfitCategory(item.getCategory())
                    && !OutfitCategories.isOutfitCategory(oldItem.getCategory())) {
                log.info("商品类目变更为穿搭类目，触发 Qdrant 同步: itemId={}, oldCat={}, newCat={}",
                        item.getId(), oldItem.getCategory(), item.getCategory());
                sendItemUpsertSync(item.getId(), true, ALL_FIELDS_CHANGED);
            }
            return ok;
        }

        // 识别本次 updateById 实际变更的字段（用于消费侧决定是否重新 encode）
        List<String> changedFields = detectChangedFields(oldItem, item);

        boolean ok = super.updateById(item);
        if (ok && item.getId() != null) {
            // updateById 可能只更新部分字段（如上下架只设 status），需查 DB 拿完整数据
            // isActive = (status == 1)，下架(status=2)/删除(status=3) 都视为软删除
            Item latest = getById(item.getId());
            if (latest != null) {
                boolean isActive = latest.getStatus() != null && latest.getStatus() == 1;
                // 类目从穿搭改为非穿搭：发 isActive=false 软删除 Qdrant 中的向量
                if (item.getCategory() != null
                        && !OutfitCategories.isOutfitCategory(item.getCategory())) {
                    isActive = false;
                    log.info("商品类目从穿搭改为非穿搭，触发 Qdrant 软删除: itemId={}, newCat={}",
                            item.getId(), item.getCategory());
                }
                sendItemUpsertSync(latest.getId(), isActive, changedFields);
            }
        }
        return ok;
    }

    @Override
    @Transactional
    public boolean removeById(java.io.Serializable id) {
        // 1. 物理删除前先查商品名（用于订单快照前缀）
        Long itemId = (id instanceof Long) ? (Long) id : Long.valueOf(id.toString());
        Item existing = itemId != null ? getById(itemId) : null;
        String itemName = (existing != null) ? existing.getName() : null;

        // 2. 物理删除 item 记录
        boolean ok = super.removeById(id);
        if (ok && itemId != null) {
            // 3. 同步清理 EAV 属性（spu_attr_value）— 避免孤儿数据
            try {
                spuAttrValueMapper.delete(
                        new LambdaQueryWrapper<SpuAttrValue>().eq(SpuAttrValue::getSpuId, itemId));
            } catch (Exception e) {
                log.warn("清理 spu_attr_value 失败, itemId={}, error={}", itemId, e.getMessage());
            }
            // 4. 同步 Qdrant 向量库
            sendItemDeleteSync(itemId);
            // 5. 通知 trade-service 标记 order_detail 快照（事务提交后异步调，避免事务回滚后误调）
            if (existing != null) {
                final String finalItemName = itemName;
                registerAfterCommit(() -> {
                    try {
                        com.hmall.api.dto.ItemDeletedMessage msg =
                                new com.hmall.api.dto.ItemDeletedMessage(itemId, finalItemName);
                        tradeClient.markItemDeletedInOrders(msg);
                        log.info("已通知 trade-service 标记订单快照: itemId={}, itemName={}", itemId, finalItemName);
                    } catch (Exception e) {
                        log.error("通知 trade-service 标记订单快照失败, itemId={}", itemId, e);
                    }
                });
            }
        }
        return ok;
    }

    /**
     * 发送商品 upsert 同步消息（事务提交后异步发）
     *
     * @param itemId        商品ID
     * @param isActive      true=上架同步（写入 Qdrant），false=下架软删除（Qdrant 中标记 inactive）
     * @param fieldsChanged 本次变更的字段列表（如 [image,price,stock]），消费侧仅 image 变更时才重新 encode
     */
    private void sendItemUpsertSync(Long itemId, boolean isActive, List<String> fieldsChanged) {
        registerAfterCommit(() -> {
            try {
                // 重新查 DB 拿完整字段（color/season/category/price/image/stock）
                Item item = getById(itemId);
                if (item == null) {
                    log.warn("发商品同步消息跳过，商品不存在: itemId={}", itemId);
                    return;
                }
                // P0 穿搭类目过滤：再次校验（事务后可能被并发改类目）
                if (!OutfitCategories.isOutfitCategory(item.getCategory())) {
                    log.debug("非穿搭类目，跳过 Qdrant 同步: itemId={}, category={}", itemId, item.getCategory());
                    return;
                }
                ItemSyncMessage msg = buildSyncMessage(item, isActive, fieldsChanged);
                rabbitMqHelper.sendMessage(
                        MqConstants.ITEM_SYNC_EXCHANGE,
                        MqConstants.ITEM_SYNC_UPSERT_KEY,
                        msg
                );
                log.info("已发商品 upsert 同步消息: itemId={}, isActive={}, color={}, season={}, stock={}, fieldsChanged={}",
                        itemId, isActive, msg.getColor(), msg.getSeason(), msg.getStock(), fieldsChanged);
            } catch (Exception e) {
                log.error("发商品 upsert 同步消息失败: itemId={}", itemId, e);
            }
        });
    }

    /**
     * 发送商品 delete 同步消息（物理删除，Qdrant 中删除对应 point）
     */
    private void sendItemDeleteSync(Long itemId) {
        registerAfterCommit(() -> {
            try {
                ItemSyncMessage msg = new ItemSyncMessage();
                msg.setItemId(itemId);
                rabbitMqHelper.sendMessage(
                        MqConstants.ITEM_SYNC_EXCHANGE,
                        MqConstants.ITEM_SYNC_DELETE_KEY,
                        msg
                );
                log.info("已发商品 delete 同步消息: itemId={}", itemId);
            } catch (Exception e) {
                log.error("发商品 delete 同步消息失败: itemId={}", itemId, e);
            }
        });
    }

    /**
     * 注册事务提交后回调；无事务时立即执行
     */
    private void registerAfterCommit(Runnable action) {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    action.run();
                }
            });
        } else {
            action.run();
        }
    }

    /** 全字段变更标记（新增商品或类目变更时使用） */
    private static final List<String> ALL_FIELDS_CHANGED = Collections.unmodifiableList(
            Arrays.asList("name", "image", "price", "stock", "category", "status", "color", "season", "style_tags")
    );

    /**
     * 触发重新 encode 的字段
     * <p>纯文本向量模式下，name/category/color/season/style_tags 变更都需要重新 encode（影响检索文本）
     * <p>image 字段保留是为了向后兼容（实际不再触发图片编码，但消费侧会据此判断是否重新 encode）
     */
    private static final Set<String> VECTOR_AFFECTING_FIELDS = new HashSet<>(Arrays.asList(
            "name", "image", "category", "color", "season", "style_tags"
    ));

    /**
     * 识别本次 updateById 实际变更的字段
     * <p>通过对比 oldItem 和入参 item 的非空字段，判断哪些字段被修改。
     * <p>MyBatis-Plus updateById 默认只更新非 null 字段，因此入参 null 字段视为"未改"。
     * <p>注意：color/season/style_tags 已移入 EAV 表（spu_attr_value），item 表不再有这些列，
     * 故此处仅检测 item 表字段。EAV 属性变更由应用层显式调用同步方法触发全量更新。
     */
    private List<String> detectChangedFields(Item oldItem, Item newItem) {
        List<String> changed = new ArrayList<>();
        if (newItem.getName() != null && !newItem.getName().equals(oldItem.getName())) {
            changed.add("name");
        }
        if (newItem.getImage() != null && !newItem.getImage().equals(oldItem.getImage())) {
            changed.add("image");
        }
        if (newItem.getPrice() != null && !newItem.getPrice().equals(oldItem.getPrice())) {
            changed.add("price");
        }
        if (newItem.getStock() != null && !newItem.getStock().equals(oldItem.getStock())) {
            changed.add("stock");
        }
        if (newItem.getCategory() != null && !newItem.getCategory().equals(oldItem.getCategory())) {
            changed.add("category");
        }
        if (newItem.getStatus() != null && !newItem.getStatus().equals(oldItem.getStatus())) {
            changed.add("status");
        }
        return changed.isEmpty() ? ALL_FIELDS_CHANGED : changed;
    }

    /**
     * 构造商品同步消息（从 Item PO 提取基础字段，从 EAV 表查询 color/season/style_tags）
     * <p>color/season/style_tags 均存文本值于 spu_attr_value 表：
     * <ul>
     *   <li>颜色(attribute_id=1)：存文本值（如 '红色'），直接返回</li>
     *   <li>季节(attribute_id=4)：存文本值（如 'summer'），直接返回</li>
     *   <li>风格(attribute_id=5)：存 JSON 数组文本（如 ["休闲","通勤"]），解析为 List</li>
     * </ul>
     * <p>resolveAttrValue 兼容旧的 attribute_value.id 存储（Long.parseLong 成功时查字典取实际值）。
     */
    private ItemSyncMessage buildSyncMessage(Item item, boolean isActive, List<String> fieldsChanged) {
        // shopId 暂未实现店铺管理，默认 0 表示平台商品（Python 消费侧默认 0）
        Long shopId = (item.getCreater() != null) ? item.getCreater() : 0L;
        // stock P1 优化：填入库存数量，Qdrant payload 存库存，节点2 filter stock>0
        Integer stock = item.getStock() != null ? item.getStock() : 0;

        // 从 EAV 表查询 color/season/style_tags
        EavAttrs eav = loadEavAttrs(item.getId());

        return new ItemSyncMessage(
                item.getId(),
                shopId,
                item.getName(),      // 商品名称（纯文本向量检索的核心文本）
                item.getCategory(),
                eav.color,           // 颜色（中文，如 红色），来自 attribute_value.value
                eav.season,          // 季节（如 summer），来自 attribute_value.value
                item.getPrice(),
                isActive,
                item.getImage(),
                eav.styleTags,       // 风格标签列表，来自 spu_attr_value.value（JSON数组）
                stock,
                fieldsChanged,
                // 性别过滤扩展（2026-07-27）：透传商品适用性别到 Qdrant payload，
                // 节点2 据此过滤 target_gender IN (user_gender, "unisex")，避免跨性别推荐
                item.getTargetGender()
        );
    }

    /**
     * 从 spu_attr_value 表加载 SPU 的 color/season/style_tags 属性
     * <p>color/season 存文本值（如 '白色'/'summer'），resolveAttrValue 直接返回
     * <p>style_tags 存 JSON 数组文本（如 '["休闲","通勤"]'），直接解析
     * <p>resolveAttrValue 兼容旧的 attribute_value.id 存储（数字时查字典取实际值）
     */
    private EavAttrs loadEavAttrs(Long spuId) {
        EavAttrs result = new EavAttrs();
        if (spuId == null) {
            return result;
        }
        try {
            // 查询该 SPU 的颜色/季节/风格属性
            List<SpuAttrValue> attrs = spuAttrValueMapper.selectList(
                    new LambdaQueryWrapper<SpuAttrValue>()
                            .eq(SpuAttrValue::getSpuId, spuId)
                            .in(SpuAttrValue::getAttributeId,
                                    Arrays.asList(ATTR_ID_COLOR, ATTR_ID_SEASON, ATTR_ID_STYLE))
            );
            if (attrs.isEmpty()) {
                return result;
            }

            // 收集需要二次查询的 attribute_value.id（颜色/季节）
            List<Long> attrValueIds = new ArrayList<>();
            Map<Long, SpuAttrValue> attrIdToSpuAttr = new HashMap<>();
            for (SpuAttrValue sav : attrs) {
                attrIdToSpuAttr.put(sav.getAttributeId(), sav);
                if (sav.getAttributeId().equals(ATTR_ID_COLOR) || sav.getAttributeId().equals(ATTR_ID_SEASON)) {
                    try {
                        attrValueIds.add(Long.parseLong(sav.getValue()));
                    } catch (NumberFormatException ignore) {
                        // value 不是数字（可能是直接存的文本值），跳过
                    }
                }
            }

            // 批量查询 attribute_value 取实际值
            Map<Long, String> attrValueMap = new HashMap<>();
            if (!attrValueIds.isEmpty()) {
                List<AttributeValue> values = attributeValueMapper.selectBatchIds(attrValueIds);
                for (AttributeValue av : values) {
                    attrValueMap.put(av.getId(), av.getValue());
                }
            }

            // 填充 color
            SpuAttrValue colorSav = attrIdToSpuAttr.get(ATTR_ID_COLOR);
            if (colorSav != null) {
                result.color = resolveAttrValue(colorSav, attrValueMap);
            }

            // 填充 season
            SpuAttrValue seasonSav = attrIdToSpuAttr.get(ATTR_ID_SEASON);
            if (seasonSav != null) {
                result.season = resolveAttrValue(seasonSav, attrValueMap);
            }

            // 填充 styleTags（JSON 数组文本，直接解析）
            SpuAttrValue styleSav = attrIdToSpuAttr.get(ATTR_ID_STYLE);
            if (styleSav != null && styleSav.getValue() != null) {
                try {
                    result.styleTags = JSON.readValue(styleSav.getValue(),
                            new TypeReference<List<String>>() {});
                } catch (Exception e) {
                    log.warn("解析风格标签 JSON 失败，使用空列表: spuId={}, value={}", spuId, styleSav.getValue());
                }
            }
        } catch (Exception e) {
            log.error("加载 SPU EAV 属性失败: spuId={}", spuId, e);
        }
        return result;
    }

    /**
     * 解析 spu_attr_value.value：
     * 若 value 是数字（attribute_value.id），从 attrValueMap 取实际值；
     * 否则直接返回 value 本身（文本属性直接存值）
     */
    private String resolveAttrValue(SpuAttrValue sav, Map<Long, String> attrValueMap) {
        String v = sav.getValue();
        if (v == null) {
            return null;
        }
        try {
            Long avId = Long.parseLong(v);
            String real = attrValueMap.get(avId);
            return real != null ? real : v;
        } catch (NumberFormatException e) {
            // 非数字，说明直接存的是文本值
            return v;
        }
    }

    /** EAV 属性临时容器（内部使用） */
    private static class EavAttrs {
        String color = null;
        String season = null;
        List<String> styleTags = Collections.emptyList();
    }


    @Override
    @Transactional
    public void deductStock(List<OrderDetailDTO> items) {
        for (OrderDetailDTO item : items) {
            int rows = baseMapper.updateStock(item);
            if (rows == 0) {
                throw new BizIllegalException("库存不足！");
            }
        }
        // 失效库存缓存，保证 AI 随心搭读到最新库存
        invalidateStockCache(items.stream().map(OrderDetailDTO::getItemId).collect(Collectors.toList()));
    }

    @Override
    public List<ItemDTO> queryItemByIds(Collection<Long> ids) {
        return BeanUtils.copyList(listByIds(ids), ItemDTO.class);
    }

    @Override
    @Transactional
    public void restoreStock(List<OrderDetailDTO> items) {
        for (OrderDetailDTO item : items) {
            // 商品已被删除则跳过，下架状态仍可恢复库存
            Item existItem = getById(item.getItemId());
            if (existItem == null) {
                log.warn("恢复库存跳过，商品已删除，itemId={}", item.getItemId());
                continue;
            }
            int rows = baseMapper.restoreStock(item);
            if (rows == 0) {
                log.warn("恢复库存未生效，itemId={}", item.getItemId());
            }
        }
        // 失效库存缓存，保证 AI 随心搭读到最新库存
        invalidateStockCache(items.stream().map(OrderDetailDTO::getItemId).collect(Collectors.toList()));
    }

    @Override
    public Page<Item> queryMerchantPage(int page, int size, String keyword, Long merchantId) {
        LambdaQueryWrapper<Item> wrapper = new LambdaQueryWrapper<>();
        wrapper.ne(Item::getStatus, 3);
        if (merchantId != null) {
            wrapper.eq(Item::getCreater, merchantId);
        }
        if (keyword != null && !keyword.isEmpty()) {
            wrapper.like(Item::getName, keyword);
        }
        wrapper.orderByAsc(Item::getStock);
        return page(new Page<>(page, size), wrapper);
    }

    @Override
    public Page<Item> queryAdminPage(int page, int size, String name, Integer status, Integer itemType, Long merchantId) {
        LambdaQueryWrapper<Item> wrapper = new LambdaQueryWrapper<>();
        if (merchantId != null) {
            wrapper.eq(Item::getCreater, merchantId);
        }
        if (name != null && !name.isEmpty()) {
            wrapper.like(Item::getName, name);
        }
        if (status != null) {
            wrapper.eq(Item::getStatus, status);
        } else {
            // 默认不显示已删除的商品
            wrapper.ne(Item::getStatus, 3);
        }
        if (itemType != null) {
            wrapper.eq(Item::getItemType, itemType);
        }
        wrapper.orderByDesc(Item::getUpdateTime);
        return page(new Page<>(page, size), wrapper);
    }

    @Override
    public List<Item> getLowStockItems(int threshold, Long merchantId) {
        LambdaQueryWrapper<Item> wrapper = new LambdaQueryWrapper<Item>()
                .ne(Item::getStatus, 3)
                .le(Item::getStock, threshold);
        if (merchantId != null) {
            wrapper.eq(Item::getCreater, merchantId);
        }
        return list(wrapper.orderByAsc(Item::getStock));
    }

    @Override
    @Transactional
    public void adjustStock(Long itemId, int targetStock) {
        if (targetStock < 0) {
            throw new BadRequestException("库存不能为负数");
        }
        Item item = getById(itemId);
        if (item == null) {
            throw new BadRequestException("商品不存在");
        }
        lambdaUpdate()
                .eq(Item::getId, itemId)
                .set(Item::getStock, targetStock)
                .update();
        log.info("库存调整: itemId={}, 原库存={}, 新库存={}", itemId, item.getStock(), targetStock);
        // P1 修复：补货/缺货场景同步到 Qdrant
        // 避免补货后 MySQL stock 已更新，但 Qdrant payload.stock 仍为旧值（0），
        // AI 推荐按 stock>0 过滤会把刚补货的商品误判为缺货而排除。
        // sendItemUpsertSync 内部已做穿搭类目过滤 + 事务提交后异步发送，非穿搭类目会自动跳过。
        // isActive 判定：商品上架(status=1) 且 新库存 > 0 时为 true，否则 Qdrant 中标记为下架。
        boolean isActive = targetStock > 0
                && item.getStatus() != null
                && item.getStatus() == 1;
        sendItemUpsertSync(itemId, isActive, Collections.singletonList("stock"));
        // 失效库存缓存，保证 AI 随心搭读到最新库存
        invalidateStockCache(Collections.singletonList(itemId));
    }

    @Override
    public long countByStatus(Integer status, Long merchantId) {
        return count(new LambdaQueryWrapper<Item>()
                .eq(Item::getStatus, status)
                .eq(merchantId != null, Item::getCreater, merchantId));
    }

    // ============================================================
    // EAV 属性读写（保证前后端数据一致性）
    // ============================================================
    // item 表已移除 color/season/style_tags/sizes/material 冗余字段，
    // 改用 spu_attr_value 表存储。以下方法封装 EAV 属性的 CRUD，
    // 使 Controller 层可像操作普通字段一样读写这些属性。

    /** 全部 EAV 属性ID列表（用于批量查询/删除） */
    private static final List<Long> ALL_EAV_ATTR_IDS = Collections.unmodifiableList(
            Arrays.asList(ATTR_ID_COLOR, ATTR_ID_SIZE, ATTR_ID_MATERIAL, ATTR_ID_SEASON, ATTR_ID_STYLE)
    );

    @Override
    @Transactional
    public void saveItemWithEav(Item item, ItemDTO dto) {
        // 1. 写 item 表（内部已处理 Qdrant 同步注册）
        save(item);
        // 2. 写 EAV 属性表
        saveSpuAttrValues(item.getId(), dto);
    }

    @Override
    @Transactional
    public void updateItemWithEav(Item item, ItemDTO dto) {
        // 1. 更新 item 表（内部已处理 Qdrant 同步注册）
        //    EAV 属性变更后，updateById 的 detectChangedFields 返回 ALL_FIELDS_CHANGED，
        //    after-commit 回调中 buildSyncMessage → loadEavAttrs 会读取最新的 EAV 值
        updateById(item);
        // 2. 更新 EAV 属性表（先删后插）
        upsertSpuAttrValues(item.getId(), dto);
    }

    /**
     * 保存 SPU 属性值到 spu_attr_value 表（新增商品时调用）
     */
    private void saveSpuAttrValues(Long spuId, ItemDTO dto) {
        if (spuId == null || dto == null) return;
        for (SpuAttrValue attr : buildSpuAttrValues(spuId, dto)) {
            spuAttrValueMapper.insert(attr);
        }
    }

    /**
     * 更新 SPU 属性值（先删后插，编辑商品时调用）
     */
    private void upsertSpuAttrValues(Long spuId, ItemDTO dto) {
        if (spuId == null || dto == null) return;
        // 先删除该 SPU 的所有 EAV 属性值
        spuAttrValueMapper.delete(new LambdaQueryWrapper<SpuAttrValue>()
                .eq(SpuAttrValue::getSpuId, spuId)
                .in(SpuAttrValue::getAttributeId, ALL_EAV_ATTR_IDS));
        // 再插入新值
        for (SpuAttrValue attr : buildSpuAttrValues(spuId, dto)) {
            spuAttrValueMapper.insert(attr);
        }
    }

    /**
     * 从 DTO 构建 SpuAttrValue 列表（仅非空字段）
     * <p>color/season/material 存文本值；styleTags/sizes 存 JSON 数组文本（前端已 stringify）
     */
    private List<SpuAttrValue> buildSpuAttrValues(Long spuId, ItemDTO dto) {
        List<SpuAttrValue> attrs = new ArrayList<>();
        LocalDateTime now = LocalDateTime.now();
        if (isNotEmpty(dto.getColor())) {
            attrs.add(newSpuAttr(spuId, ATTR_ID_COLOR, dto.getColor(), now));
        }
        if (isNotEmpty(dto.getSizes())) {
            attrs.add(newSpuAttr(spuId, ATTR_ID_SIZE, dto.getSizes(), now));
        }
        if (isNotEmpty(dto.getMaterial())) {
            attrs.add(newSpuAttr(spuId, ATTR_ID_MATERIAL, dto.getMaterial(), now));
        }
        if (isNotEmpty(dto.getSeason())) {
            attrs.add(newSpuAttr(spuId, ATTR_ID_SEASON, dto.getSeason(), now));
        }
        if (isNotEmpty(dto.getStyleTags())) {
            attrs.add(newSpuAttr(spuId, ATTR_ID_STYLE, dto.getStyleTags(), now));
        }
        return attrs;
    }

    private SpuAttrValue newSpuAttr(Long spuId, Long attrId, String value, LocalDateTime now) {
        SpuAttrValue sav = new SpuAttrValue();
        sav.setSpuId(spuId);
        sav.setAttributeId(attrId);
        sav.setValue(value);
        sav.setCreateTime(now);
        return sav;
    }

    private static boolean isNotEmpty(String s) {
        return s != null && !s.isEmpty();
    }

    @Override
    public void fillEavAttrs(ItemDTO dto) {
        if (dto == null || dto.getId() == null) return;
        // 查询该 SPU 的所有 EAV 属性
        List<SpuAttrValue> attrs = spuAttrValueMapper.selectList(
                new LambdaQueryWrapper<SpuAttrValue>()
                        .eq(SpuAttrValue::getSpuId, dto.getId())
                        .in(SpuAttrValue::getAttributeId, ALL_EAV_ATTR_IDS));
        Map<Long, SpuAttrValue> attrMap = new HashMap<>();
        for (SpuAttrValue sav : attrs) {
            attrMap.put(sav.getAttributeId(), sav);
        }
        populateDtoFromEav(dto, attrMap);
    }

    @Override
    public void fillEavAttrsBatch(List<ItemDTO> dtos) {
        if (dtos == null || dtos.isEmpty()) return;
        // 收集 spuId
        List<Long> spuIds = new ArrayList<>();
        for (ItemDTO dto : dtos) {
            if (dto.getId() != null) spuIds.add(dto.getId());
        }
        if (spuIds.isEmpty()) return;

        // 批量查询所有 EAV 属性（避免 N+1）
        List<SpuAttrValue> allAttrs = spuAttrValueMapper.selectList(
                new LambdaQueryWrapper<SpuAttrValue>()
                        .in(SpuAttrValue::getSpuId, spuIds)
                        .in(SpuAttrValue::getAttributeId, ALL_EAV_ATTR_IDS));

        // 按 spuId 分组
        Map<Long, Map<Long, SpuAttrValue>> spuAttrMap = new HashMap<>();
        for (SpuAttrValue sav : allAttrs) {
            spuAttrMap.computeIfAbsent(sav.getSpuId(), k -> new HashMap<>())
                    .put(sav.getAttributeId(), sav);
        }

        // 填充每个 DTO
        for (ItemDTO dto : dtos) {
            if (dto.getId() == null) continue;
            Map<Long, SpuAttrValue> attrMap = spuAttrMap.get(dto.getId());
            if (attrMap != null) {
                populateDtoFromEav(dto, attrMap);
            }
        }
    }

    /**
     * 从 EAV 属性 map 填充 DTO
     * <p>color/season 存文本值，resolveAttrValue 直接返回；兼容旧的 attribute_value.id 存储
     */
    private void populateDtoFromEav(ItemDTO dto, Map<Long, SpuAttrValue> attrMap) {
        if (attrMap == null || attrMap.isEmpty()) return;

        // 收集需要二次查询的 attribute_value.id（颜色/季节）
        List<Long> attrValueIds = new ArrayList<>();
        SpuAttrValue colorSav = attrMap.get(ATTR_ID_COLOR);
        SpuAttrValue seasonSav = attrMap.get(ATTR_ID_SEASON);
        if (colorSav != null) collectAttrValueId(colorSav, attrValueIds);
        if (seasonSav != null) collectAttrValueId(seasonSav, attrValueIds);

        // 批量查询 attribute_value 取实际值
        Map<Long, String> attrValueMap = new HashMap<>();
        if (!attrValueIds.isEmpty()) {
            List<AttributeValue> values = attributeValueMapper.selectBatchIds(attrValueIds);
            for (AttributeValue av : values) {
                attrValueMap.put(av.getId(), av.getValue());
            }
        }

        // 填充 DTO（color/season 走 resolveAttrValue 兼容 id/文本两种存储）
        if (colorSav != null) dto.setColor(resolveAttrValue(colorSav, attrValueMap));
        if (seasonSav != null) dto.setSeason(resolveAttrValue(seasonSav, attrValueMap));

        // styleTags/sizes/material 直接取文本值
        SpuAttrValue styleSav = attrMap.get(ATTR_ID_STYLE);
        if (styleSav != null) dto.setStyleTags(styleSav.getValue());

        SpuAttrValue sizeSav = attrMap.get(ATTR_ID_SIZE);
        if (sizeSav != null) dto.setSizes(sizeSav.getValue());

        SpuAttrValue materialSav = attrMap.get(ATTR_ID_MATERIAL);
        if (materialSav != null) dto.setMaterial(materialSav.getValue());
    }

    /**
     * 收集 spu_attr_value.value 中的 attribute_value.id（仅数字值）
     */
    private void collectAttrValueId(SpuAttrValue sav, List<Long> ids) {
        if (sav.getValue() == null) return;
        try {
            ids.add(Long.parseLong(sav.getValue()));
        } catch (NumberFormatException ignore) {
            // 非数字（直接存的文本值），跳过
        }
    }

    // ===== v6 工具拓展：库存批量查询 + 销量趋势查询（供 Python ai-outfit 调用）=====

    /** Redis 库存缓存 key 前缀（与 item-service 自身缓存对齐） */
    private static final String STOCK_CACHE_KEY_PREFIX = "item:stock:";
    /** 库存缓存 TTL：5 分钟（秒） */
    private static final long STOCK_CACHE_TTL_SECONDS = 300;

    @Override
    public Map<Long, Integer> batchQueryInventory(List<Long> itemIds) {
        if (itemIds == null || itemIds.isEmpty()) {
            return Collections.emptyMap();
        }
        Map<Long, Integer> result = new HashMap<>();
        // 1. 先批量查 Redis 缓存
        List<String> keys = new ArrayList<>(itemIds.size());
        for (Long id : itemIds) {
            keys.add(STOCK_CACHE_KEY_PREFIX + id);
        }
        List<String> cachedValues = stringRedisTemplate.opsForValue().multiGet(keys);
        List<Long> missedIds = new ArrayList<>();
        for (int i = 0; i < itemIds.size(); i++) {
            String val = cachedValues.get(i);
            if (val != null) {
                try {
                    result.put(itemIds.get(i), Integer.parseInt(val));
                } catch (NumberFormatException ignore) {
                    missedIds.add(itemIds.get(i));
                }
            } else {
                missedIds.add(itemIds.get(i));
            }
        }
        // 2. 缓存未命中的查数据库
        if (!missedIds.isEmpty()) {
            List<Item> items = listByIds(missedIds);
            Map<Long, Integer> dbStockMap = new HashMap<>();
            for (Item item : items) {
                int stock = item.getStock() != null ? item.getStock() : 0;
                dbStockMap.put(item.getId(), stock);
                result.put(item.getId(), stock);
            }
            // 商品不存在的填 0
            for (Long id : missedIds) {
                if (!dbStockMap.containsKey(id)) {
                    result.put(id, 0);
                }
            }
            // 3. 回填 Redis 缓存（pipeline 减少网络往返）
            org.springframework.data.redis.core.RedisCallback<Object> pipelineAction = connection -> {
                org.springframework.data.redis.connection.StringRedisConnection conn =
                        (org.springframework.data.redis.connection.StringRedisConnection) connection;
                for (Map.Entry<Long, Integer> e : dbStockMap.entrySet()) {
                    conn.setEx(STOCK_CACHE_KEY_PREFIX + e.getKey(),
                            STOCK_CACHE_TTL_SECONDS, String.valueOf(e.getValue()));
                }
                // 不存在的商品也缓存 0（防穿透，TTL 缩短到 60s）
                for (Long id : missedIds) {
                    if (!dbStockMap.containsKey(id)) {
                        conn.setEx(STOCK_CACHE_KEY_PREFIX + id, 60, "0");
                    }
                }
                return null;
            };
            try {
                stringRedisTemplate.executePipelined(pipelineAction);
            } catch (Exception e) {
                log.warn("库存缓存回填失败（不影响主流程）: {}", e.getMessage());
            }
        }
        return result;
    }

    /**
     * 失效库存缓存（在库存变更时调用，保证 AI 随心搭读到最新库存）
     * key 格式：item:stock:{itemId}
     */
    private void invalidateStockCache(Collection<Long> itemIds) {
        if (itemIds == null || itemIds.isEmpty()) return;
        try {
            List<String> keys = new ArrayList<>(itemIds.size());
            for (Long id : itemIds) {
                keys.add(STOCK_CACHE_KEY_PREFIX + id);
            }
            stringRedisTemplate.delete(keys);
        } catch (Exception e) {
            log.warn("失效库存缓存失败（不影响主流程）: {}", e.getMessage());
        }
    }

    @Override
    public List<ItemDTO> getTrendingItems(String category, int days, int topK) {
        if (topK <= 0) topK = 50;
        if (days <= 0) days = 30;
        // 基于商品累计销量（item.sold 字段）排序，反映长期热销趋势
        // 注：days 参数保留为向后兼容，当前实现不按时间窗口过滤（避免 join order 表的复杂度）
        //     如需精确的"近 N 天"销量，需联查 order_detail 表按 create_time 聚合
        LambdaQueryWrapper<Item> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Item::getStatus, 1);  // 仅上架商品
        if (category != null && !category.isEmpty()) {
            wrapper.eq(Item::getCategory, category);
        }
        wrapper.orderByDesc(Item::getSold);
        wrapper.last("LIMIT " + topK);
        List<Item> items = list(wrapper);
        return BeanUtils.copyList(items, ItemDTO.class);
    }
}
