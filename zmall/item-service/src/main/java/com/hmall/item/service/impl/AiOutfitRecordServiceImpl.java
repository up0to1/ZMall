package com.hmall.item.service.impl;

import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.api.client.WardrobeClient;
import com.hmall.api.dto.AiOutfitHistoryDTO;
import com.hmall.api.dto.AiOutfitRecordCreateDTO;
import com.hmall.api.dto.AiOutfitRecordDTO;
import com.hmall.api.dto.WardrobeDTO;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.UserContext;
import com.hmall.item.domain.po.AiOutfitRecord;
import com.hmall.item.domain.po.SystemModelImage;
import com.hmall.item.mapper.AiOutfitRecordMapper;
import com.hmall.item.mapper.SystemModelImageMapper;
import com.hmall.item.service.IAiOutfitRecordService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.List;

/**
 * AI 随心搭效果图入库服务实现（v3 新增）
 *
 * <p>设计文档 §3.3.1 ⑨A/⑨B + §3.3.4 + §3.16.2
 *
 * <p>写入策略：仅用户满意的套装入库（accepted=1）；不满意的不入库，避免数据膨胀。
 * <p>清理策略：永久保留，仅用户主动删除（"我的搭配历史"页面提供删除按钮）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AiOutfitRecordServiceImpl extends ServiceImpl<AiOutfitRecordMapper, AiOutfitRecord>
        implements IAiOutfitRecordService {

    private static final String ACCEPTED_ACTION_CART = "cart";
    private static final String ACCEPTED_ACTION_ORDER = "order";
    private static final String ACCEPTED_ACTION_PENDING = "pending";
    private static final String ACCEPTED_ACTION_REJECTED = "rejected";
    private static final String ACCEPTED_ACTION_SAVED = "saved";

    private final WardrobeClient wardrobeClient;
    private final SystemModelImageMapper systemModelImageMapper;

    @Override
    public AiOutfitRecordDTO createRecord(AiOutfitRecordCreateDTO dto) {
        // 1.基础校验
        validateCreateDto(dto);

        // 2.落库（accepted 优先用 dto 传入值，为空默认 1=满意采纳）
        int accepted = dto.getAccepted() != null ? dto.getAccepted() : 1;

        // upsert：按 taskId + outfitIndex 查找现有记录
        // 一阶段直出已入库 accepted=0，用户采纳时调本接口传 accepted=1 → 更新为已采纳
        AiOutfitRecord existing = lambdaQuery()
                .eq(AiOutfitRecord::getTaskId, dto.getTaskId())
                .eq(AiOutfitRecord::getOutfitIndex, dto.getOutfitIndex())
                .one();
        if (existing != null) {
            // 缓存更新前的原始照片/模特图（syncWardrobeOnSatisfied 写衣橱用，避免被 dto 空值覆盖）
            String userPhotoBeforeUpdate = existing.getUserPhotoUrl();
            Long modelImageIdBeforeUpdate = existing.getModelImageId();
            String systemModelImageBeforeUpdate = existing.getSystemModelImageUrl();
            // 联动删除衣橱：满意(1) → 取消满意/不满意(非1) 时，删除 user_wardrobe 中
            // 该搭配记录对应的条目（item_type=4，record_id=existing.id）
            if (existing.getAccepted() != null && existing.getAccepted() == 1 && accepted != 1) {
                try {
                    wardrobeClient.removeByRecord(existing.getId());
                    log.info("取消满意联动删除衣橱条目: recordId={}", existing.getId());
                } catch (Exception ex) {
                    // 失败不影响记录状态更新主流程（FallbackFactory 兜底，此处再兜一层）
                    log.warn("取消满意联动删除衣橱条目失败: recordId={}, err={}", existing.getId(), ex.getMessage());
                }
            }
            existing.setAccepted(accepted);
            existing.setAcceptedAction(dto.getAcceptedAction());
            existing.setOutfitJson(dto.getOutfitJson());
            existing.setVtonResultUrl(dto.getVtonResultUrl());
            existing.setUserPhotoUrl(dto.getUserPhotoUrl());
            existing.setModelImageSource(dto.getModelImageSource());
            existing.setModelImageId(dto.getModelImageId());
            // 系统模特图 URL：仅 dto 有值时更新（前端满意标记不传，避免覆盖历史值）
            if (dto.getSystemModelImageUrl() != null) {
                existing.setSystemModelImageUrl(dto.getSystemModelImageUrl());
            }
            existing.setCreditsConsumed(dto.getCreditsConsumed());
            existing.setUpdatedAt(LocalDateTime.now());
            updateById(existing);
            log.info("AI 随心搭效果图已更新（upsert）: id={}, taskId={}, outfitIndex={}, accepted={}",
                    existing.getId(), existing.getTaskId(), existing.getOutfitIndex(), accepted);
            // 联动写入衣橱：标记满意(accepted=1) 时把搭配效果图写入 user_wardrobe（item_type=4）
            // Python accept 流程随后调 /wardrobe/internal 幂等跳过，不重复插入
            if (accepted == 1) {
                syncWardrobeOnSatisfied(existing.getUserId(), existing.getId(), dto,
                        userPhotoBeforeUpdate, modelImageIdBeforeUpdate, systemModelImageBeforeUpdate);
            }
            return BeanUtils.copyBean(existing, AiOutfitRecordDTO.class);
        }

        // 新增记录（⑥ 用户选定模式或无现有记录时）
        AiOutfitRecord record = new AiOutfitRecord()
                .setTaskId(dto.getTaskId())
                .setUserId(dto.getUserId())
                .setRound(dto.getRound() != null ? dto.getRound() : 1)
                .setOutfitIndex(dto.getOutfitIndex())
                .setOutfitJson(dto.getOutfitJson())
                .setVtonResultUrl(dto.getVtonResultUrl())
                .setUserPhotoUrl(dto.getUserPhotoUrl())
                .setModelImageSource(dto.getModelImageSource())
                .setModelImageId(dto.getModelImageId())
                .setSystemModelImageUrl(dto.getSystemModelImageUrl())
                .setAccepted(accepted)
                .setAcceptedAction(dto.getAcceptedAction())
                .setCreditsConsumed(dto.getCreditsConsumed())
                .setCreatedAt(LocalDateTime.now())
                .setUpdatedAt(LocalDateTime.now());
        save(record);
        log.info("AI 随心搭效果图已入库: id={}, taskId={}, userId={}, outfitIndex={}, action={}, userPhotoUrl={}",
                record.getId(), record.getTaskId(), record.getUserId(),
                record.getOutfitIndex(), record.getAcceptedAction(),
                record.getUserPhotoUrl() == null ? "null" : "present");
        // 联动写入衣橱：满意(accepted=1) 时把搭配效果图写入 user_wardrobe（item_type=4）
        if (accepted == 1) {
            syncWardrobeOnSatisfied(record.getUserId(), record.getId(), dto,
                    record.getUserPhotoUrl(), record.getModelImageId(), record.getSystemModelImageUrl());
        }
        return BeanUtils.copyBean(record, AiOutfitRecordDTO.class);
    }

    /**
     * 满意联动写入衣橱（item_type=4 AI 搭配效果图）
     *
     * <p>用户标记满意（accepted=1）时调用：把搭配效果图写入 user_wardrobe，
     * 幂等由 user-service /wardrobe/internal 保证（同一 recordId 已有有效条目则跳过）。
     * 失败不影响记录状态更新主流程。
     *
     * <p>模特/原始照片（originalPhotoUrl）来源（按优先级）：
     * <ul>
     *   <li>系统默认模特图：dto.systemModelImageUrl（用户选定的初始模特图，最准确）</li>
     *   <li>真人照片模式：dto.userPhotoUrl（用户自拍照）</li>
     *   <li>回退：按 modelImageId 查 system_model_image 表取模特图 URL</li>
     * </ul>
     */
    private void syncWardrobeOnSatisfied(Long userId, Long recordId, AiOutfitRecordCreateDTO dto,
                                         String fallbackUserPhotoUrl, Long fallbackModelImageId,
                                         String fallbackSystemModelImageUrl) {
        try {
            // 1. 模特/原始照片：优先系统默认模特图 → 用户自拍照 → 按 modelImageId 查系统模特池
            String systemModelImageUrl = dto.getSystemModelImageUrl() != null
                    ? dto.getSystemModelImageUrl() : fallbackSystemModelImageUrl;
            String originalPhotoUrl = systemModelImageUrl != null ? systemModelImageUrl
                    : (dto.getUserPhotoUrl() != null ? dto.getUserPhotoUrl() : fallbackUserPhotoUrl);
            Long modelImageId = dto.getModelImageId() != null ? dto.getModelImageId() : fallbackModelImageId;
            if (originalPhotoUrl == null && modelImageId != null) {
                try {
                    SystemModelImage model = systemModelImageMapper.selectById(modelImageId);
                    if (model != null && StrUtil.isNotBlank(model.getImageUrl())) {
                        originalPhotoUrl = model.getImageUrl();
                        log.info("衣橱模特图取自系统模特池: modelImageId={}, url={}", modelImageId, originalPhotoUrl);
                    }
                } catch (Exception ex) {
                    log.warn("查询系统模特图失败（不影响写衣橱）: modelImageId={}, err={}", modelImageId, ex.getMessage());
                }
            }
            // 2. 构造并写入衣橱
            WardrobeDTO wardrobeDto = new WardrobeDTO();
            wardrobeDto.setUserId(userId);
            wardrobeDto.setItemType(4);
            wardrobeDto.setOutfitResultUrl(dto.getVtonResultUrl());
            wardrobeDto.setOriginalPhotoUrl(originalPhotoUrl);
            wardrobeDto.setOutfitJson(dto.getOutfitJson());
            wardrobeDto.setRecordId(recordId);
            WardrobeDTO saved = wardrobeClient.addWardrobeOutfit(wardrobeDto);
            if (saved != null) {
                log.info("满意自动写入衣橱: recordId={}, wardrobeId={}", recordId, saved.getId());
            }
        } catch (Exception ex) {
            // 失败不影响记录状态更新主流程（FallbackFactory 兜底，此处再兜一层）
            log.warn("满意自动写入衣橱失败（不影响记录更新）: recordId={}, err={}", recordId, ex.getMessage());
        }
    }

    @Override
    public List<AiOutfitRecordDTO> queryMyRecords(Integer accepted) {
        Long userId = UserContext.getUser();
        if (userId == null) {
            return Collections.emptyList();
        }
        LambdaQueryWrapper<AiOutfitRecord> wrapper = new LambdaQueryWrapper<AiOutfitRecord>()
                .eq(AiOutfitRecord::getUserId, userId)
                .orderByDesc(AiOutfitRecord::getCreatedAt);
        if (accepted != null) {
            wrapper.eq(AiOutfitRecord::getAccepted, accepted);
        }
        wrapper.last("LIMIT 200");
        List<AiOutfitRecord> list = list(wrapper);
        return BeanUtils.copyList(list, AiOutfitRecordDTO.class);
    }

    @Override
    public AiOutfitRecordDTO queryById(Long id) {
        Long userId = UserContext.getUser();
        AiOutfitRecord record = getById(id);
        if (record == null) {
            return null;
        }
        // 权限校验：仅本人可查看（userId 为空时是内部调用，允许查看）
        if (userId != null && !userId.equals(record.getUserId())) {
            log.warn("用户尝试查看他人搭配记录: recordId={}, recordUserId={}, currentUserId={}",
                    id, record.getUserId(), userId);
            return null;
        }
        return BeanUtils.copyBean(record, AiOutfitRecordDTO.class);
    }

    @Override
    public AiOutfitRecordDTO queryByTaskAndIndex(String taskId, Integer outfitIndex) {
        if (StrUtil.isBlank(taskId) || outfitIndex == null) {
            return null;
        }
        Long userId = UserContext.getUser();
        AiOutfitRecord record = lambdaQuery()
                .eq(AiOutfitRecord::getTaskId, taskId)
                .eq(AiOutfitRecord::getOutfitIndex, outfitIndex)
                .one();
        if (record == null) {
            return null;
        }
        // 权限校验：仅本人可查看（userId 为空时是内部调用，允许查看）
        if (userId != null && !userId.equals(record.getUserId())) {
            log.warn("用户尝试按 taskId 查看他人搭配记录: taskId={}, recordUserId={}, currentUserId={}",
                    taskId, record.getUserId(), userId);
            return null;
        }
        return BeanUtils.copyBean(record, AiOutfitRecordDTO.class);
    }

    @Override
    public void deleteRecord(Long id) {
        Long userId = UserContext.getUser();
        if (userId == null) {
            throw new BizIllegalException("用户未登录");
        }
        AiOutfitRecord record = getById(id);
        if (record == null) {
            throw new BadRequestException("搭配记录不存在");
        }
        if (!userId.equals(record.getUserId())) {
            throw new BizIllegalException("无权操作：搭配记录不属于当前用户");
        }
        removeById(id);
        log.info("AI 随心搭效果图已删除: id={}, userId={}", id, userId);
    }

    @Override
    public void removeWardrobeByTask(String taskId, Integer outfitIndex) {
        Long userId = UserContext.getUser();
        if (userId == null) {
            throw new BizIllegalException("用户未登录");
        }
        if (StrUtil.isBlank(taskId) || outfitIndex == null) {
            return;
        }
        AiOutfitRecord record = lambdaQuery()
                .eq(AiOutfitRecord::getTaskId, taskId)
                .eq(AiOutfitRecord::getOutfitIndex, outfitIndex)
                .one();
        if (record == null) {
            return; // 无记录则无需删除衣橱条目
        }
        if (!userId.equals(record.getUserId())) {
            throw new BizIllegalException("无权操作：搭配记录不属于当前用户");
        }
        try {
            wardrobeClient.removeByRecord(record.getId());
            log.info("取消满意联动删除衣橱条目（结果页）: recordId={}", record.getId());
        } catch (Exception ex) {
            // 失败不影响页面交互（FallbackFactory 兜底）
            log.warn("取消满意联动删除衣橱条目失败（结果页）: recordId={}, err={}", record.getId(), ex.getMessage());
        }
    }

    @Override
    public void markOutfitOrdered(Long recordId, String taskId, Integer outfitIndex, Long orderId, Long userId) {
        if (orderId == null) {
            log.warn("标记搭配记录已下单跳过：orderId 为空");
            return;
        }
        AiOutfitRecord record = null;
        if (recordId != null) {
            record = getById(recordId);
        }
        if (record == null && StrUtil.isNotBlank(taskId) && outfitIndex != null) {
            record = lambdaQuery()
                    .eq(AiOutfitRecord::getTaskId, taskId)
                    .eq(AiOutfitRecord::getOutfitIndex, outfitIndex)
                    .one();
        }
        if (record == null) {
            log.warn("标记搭配记录已下单跳过：记录不存在 recordId={}, taskId={}, outfitIndex={}, orderId={}",
                    recordId, taskId, outfitIndex, orderId);
            return;
        }
        if (userId != null && !userId.equals(record.getUserId())) {
            log.warn("标记搭配记录已下单跳过：归属校验失败 recordId={}, orderId={}, callerUserId={}, recordUserId={}",
                    record.getId(), orderId, userId, record.getUserId());
            return;
        }
        // 幂等：同一订单重复回调跳过
        if (orderId.equals(record.getOrderId())) {
            return;
        }
        // 保存下单前状态快照（订单取消/超时回退用）；已在下单状态时保留原快照
        if (!ACCEPTED_ACTION_ORDER.equals(record.getAcceptedAction())) {
            record.setPrevAccepted(record.getAccepted());
            record.setPrevAcceptedAction(record.getAcceptedAction());
        }
        record.setAccepted(1);
        record.setAcceptedAction(ACCEPTED_ACTION_ORDER);
        record.setOrderId(orderId);
        record.setUpdatedAt(LocalDateTime.now());
        updateById(record);
        log.info("搭配记录标记已下单: recordId={}, taskId={}, outfitIndex={}, orderId={}, prevAccepted={}, prevAction={}",
                record.getId(), record.getTaskId(), record.getOutfitIndex(), orderId,
                record.getPrevAccepted(), record.getPrevAcceptedAction());
        // 联动写衣橱（下单即视为满意；/wardrobe/internal 幂等，已存在条目跳过）
        syncWardrobeOnSatisfied(record.getUserId(), record.getId(),
                buildRecordDtoForWardrobe(record),
                record.getUserPhotoUrl(), record.getModelImageId(), record.getSystemModelImageUrl());
    }

    @Override
    public void revertOutfitOrder(Long orderId, Long userId) {
        if (orderId == null) {
            return;
        }
        AiOutfitRecord record = lambdaQuery()
                .eq(AiOutfitRecord::getOrderId, orderId)
                .one();
        if (record == null) {
            log.info("回退搭配记录已下单状态跳过：无记录关联该订单 orderId={}", orderId);
            return;
        }
        if (userId != null && !userId.equals(record.getUserId())) {
            log.warn("回退搭配记录已下单状态跳过：归属校验失败 orderId={}, callerUserId={}, recordUserId={}",
                    orderId, userId, record.getUserId());
            return;
        }
        Integer prevAccepted = record.getPrevAccepted() != null ? record.getPrevAccepted() : 0;
        String prevAction = StrUtil.isNotBlank(record.getPrevAcceptedAction())
                ? record.getPrevAcceptedAction() : ACCEPTED_ACTION_PENDING;
        record.setAccepted(prevAccepted);
        record.setAcceptedAction(prevAction);
        record.setOrderId(null);
        record.setPrevAccepted(null);
        record.setPrevAcceptedAction(null);
        record.setUpdatedAt(LocalDateTime.now());
        updateById(record);
        log.info("回退搭配记录已下单状态: recordId={}, orderId={}, 恢复 accepted={}, action={}",
                record.getId(), orderId, prevAccepted, prevAction);
        // 回退后非满意 → 联动删除衣橱条目（下单时写入的）
        if (prevAccepted != 1) {
            try {
                wardrobeClient.removeByRecord(record.getId());
                log.info("回退已下单联动删除衣橱条目: recordId={}, orderId={}", record.getId(), orderId);
            } catch (Exception ex) {
                log.warn("回退已下单联动删除衣橱条目失败: recordId={}, err={}", record.getId(), ex.getMessage());
            }
        }
    }

    /** 从记录构造衣橱联动 DTO（markOutfitOrdered 复用 syncWardrobeOnSatisfied） */
    private AiOutfitRecordCreateDTO buildRecordDtoForWardrobe(AiOutfitRecord record) {
        AiOutfitRecordCreateDTO dto = new AiOutfitRecordCreateDTO();
        dto.setOutfitJson(record.getOutfitJson());
        dto.setVtonResultUrl(record.getVtonResultUrl());
        dto.setUserPhotoUrl(record.getUserPhotoUrl());
        dto.setModelImageSource(record.getModelImageSource());
        dto.setModelImageId(record.getModelImageId());
        dto.setSystemModelImageUrl(record.getSystemModelImageUrl());
        dto.setAcceptedAction(record.getAcceptedAction());
        dto.setAccepted(record.getAccepted());
        return dto;
    }

    @Override
    public List<AiOutfitHistoryDTO> queryMyHistory(String tab) {
        Long userId = UserContext.getUser();
        if (userId == null) {
            return Collections.emptyList();
        }
        // tab → SQL 条件（白名单映射，防注入）
        // 以 ai_outfit_record 为主表 LEFT JOIN ai_task，条件字段用 r. / t. 前缀
        String tabCondition;
        if ("processing".equals(tab)) {
            // 生成中：ai_task 状态 PROCESSING（风格驱动阶段二）
            // 或 用户选定模式占位记录（任务启动即入库、结果为空，成功后 upsert 更新）
            tabCondition = "AND (t.status IN ('PENDING', 'PROCESSING') "
                    + "OR r.outfit_json IS NULL OR r.outfit_json = '[]' OR r.outfit_json = '{}')";
        } else if ("accepted".equals(tab)) {
            tabCondition = "AND r.accepted = 1";
        } else if ("unaccepted".equals(tab)) {
            // 待采纳：一阶段直出自动入库 accepted=0+pending
            tabCondition = "AND (r.accepted = 0 AND r.accepted_action = 'pending')";
        } else if ("rejected".equals(tab)) {
            tabCondition = "AND r.accepted = 0 AND (r.accepted_action IS NULL OR r.accepted_action != 'pending')";
        } else if ("failed".equals(tab)) {
            tabCondition = "AND t.status IN ('FAILED', 'TIMEOUT')";
        } else {
            tabCondition = "";  // all
        }
        return baseMapper.queryMyHistory(userId, tabCondition);
    }

    private void validateCreateDto(AiOutfitRecordCreateDTO dto) {
        if (StrUtil.isBlank(dto.getAcceptedAction())) {
            throw new BadRequestException("满意动作不能为空");
        }
        if (!ACCEPTED_ACTION_CART.equals(dto.getAcceptedAction())
                && !ACCEPTED_ACTION_ORDER.equals(dto.getAcceptedAction())
                && !ACCEPTED_ACTION_PENDING.equals(dto.getAcceptedAction())
                && !ACCEPTED_ACTION_REJECTED.equals(dto.getAcceptedAction())
                && !ACCEPTED_ACTION_SAVED.equals(dto.getAcceptedAction())) {
            throw new BadRequestException("满意动作非法，仅支持 cart / order / pending / rejected / saved");
        }
        if (dto.getOutfitIndex() == null || dto.getOutfitIndex() < 0 || dto.getOutfitIndex() > 2) {
            throw new BadRequestException("套装索引非法，仅支持 0/1/2");
        }
    }
}
