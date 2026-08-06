package com.hmall.user.controller;

import cn.hutool.core.util.StrUtil;
import com.hmall.api.dto.WardrobeDTO;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.CollUtils;
import com.hmall.common.utils.UserContext;
import com.hmall.user.domain.po.Wardrobe;
import com.hmall.user.service.IWardrobeService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.stream.Collectors;

/**
 * <p>
 * 我的衣橱 前端控制器
 * </p>
 *
 * @author hmall
 */
@Slf4j
@RestController
@RequestMapping("/wardrobe")
@RequiredArgsConstructor
@Api(tags = "我的衣橱管理接口")
public class WardrobeController {

    private final IWardrobeService wardrobeService;

    @ApiOperation("查询当前用户衣橱列表")
    @GetMapping
    public List<WardrobeDTO> findMyWardrobe() {
        Long userId = UserContext.getUser();
        List<Wardrobe> list = wardrobeService.lambdaQuery()
                .eq(Wardrobe::getUserId, userId)
                .eq(Wardrobe::getIsActive, 1)
                .orderByDesc(Wardrobe::getCreateTime)
                .list();
        if (CollUtils.isEmpty(list)) {
            return CollUtils.emptyList();
        }
        return BeanUtils.copyList(list, WardrobeDTO.class);
    }

    @ApiOperation("服务间调用-查询指定用户衣橱列表")
    @GetMapping("/list")
    public List<WardrobeDTO> queryUserWardrobe(@ApiParam("用户ID") @RequestParam("userId") Long userId) {
        if (userId == null) {
            return CollUtils.emptyList();
        }
        List<Wardrobe> list = wardrobeService.lambdaQuery()
                .eq(Wardrobe::getUserId, userId)
                .eq(Wardrobe::getIsActive, 1)
                .orderByDesc(Wardrobe::getCreateTime)
                .list();
        if (CollUtils.isEmpty(list)) {
            return CollUtils.emptyList();
        }
        return BeanUtils.copyList(list, WardrobeDTO.class);
    }

    @ApiOperation("批量查询衣橱条目")
    @GetMapping("/items")
    public List<WardrobeDTO> queryWardrobeByIds(@ApiParam("衣橱条目id集合") @RequestParam("ids") List<Long> ids) {
        if (CollUtils.isEmpty(ids)) {
            return CollUtils.emptyList();
        }
        List<Wardrobe> list = wardrobeService.lambdaQuery()
                .in(Wardrobe::getId, ids)
                .eq(Wardrobe::getIsActive, 1)
                .list();
        if (CollUtils.isEmpty(list)) {
            return CollUtils.emptyList();
        }
        return BeanUtils.copyList(list, WardrobeDTO.class);
    }

    @ApiOperation("新增衣橱条目")
    @PostMapping
    public void addWardrobe(@RequestBody WardrobeDTO dto) {
        Long userId = UserContext.getUser();
        validateItemType(dto);
        Wardrobe wardrobe = BeanUtils.copyBean(dto, Wardrobe.class);
        wardrobe.setId(null);
        wardrobe.setUserId(userId);
        wardrobe.setIsActive(1);
        wardrobeService.save(wardrobe);
    }

    @ApiOperation("服务间调用-AI 满意搭配效果图写入衣橱（item_type=4，v3.1 新增）")
    @PostMapping("/internal")
    public WardrobeDTO addWardrobeOutfit(@RequestBody WardrobeDTO dto) {
        // v3.1：Python ai-outfit accept 流程在 create_outfit_record 成功后调用
        // 与 POST /wardrobe 的差异：接受显式 userId 参数，支持 item_type=4，仅服务间调用
        // 失败容忍：本接口异常会触发 Python 侧 try/except + warning 日志，不影响 accept 主流程
        if (dto == null || dto.getUserId() == null) {
            throw new BadRequestException("userId 不能为空");
        }
        if (dto.getItemType() == null || dto.getItemType() != 4) {
            throw new BadRequestException("本接口仅支持 item_type=4（AI 搭配效果图）");
        }
        // 校验 AI 搭配效果图必填字段
        if (dto.getOutfitResultUrl() == null || dto.getOutfitResultUrl().isEmpty()) {
            throw new BadRequestException("AI 搭配效果图 URL（outfitResultUrl）不能为空");
        }
        if (dto.getOutfitJson() == null || dto.getOutfitJson().isEmpty()) {
            throw new BadRequestException("AI 搭配单品详情（outfitJson）不能为空");
        }
        if (dto.getRecordId() == null) {
            throw new BadRequestException("关联搭配记录 ID（recordId）不能为空");
        }
        // 幂等：同一 recordId 已有有效衣橱条目时不重复插入（item-service 标记满意已自动写衣橱，
        // Python accept 流程再调本接口时跳过，避免重复条目）
        Wardrobe existed = wardrobeService.lambdaQuery()
                .eq(Wardrobe::getRecordId, dto.getRecordId())
                .eq(Wardrobe::getUserId, dto.getUserId())
                .eq(Wardrobe::getIsActive, 1)
                .one();
        if (existed != null) {
            // 存量修复：已存在条目缺模特/原始照片而本次提供了，则补写（历史系统模特搭配无 originalPhotoUrl）
            if (StrUtil.isNotBlank(dto.getOriginalPhotoUrl())
                    && StrUtil.isBlank(existed.getOriginalPhotoUrl())) {
                wardrobeService.lambdaUpdate()
                        .eq(Wardrobe::getId, existed.getId())
                        .set(Wardrobe::getOriginalPhotoUrl, dto.getOriginalPhotoUrl())
                        .update();
                existed.setOriginalPhotoUrl(dto.getOriginalPhotoUrl());
                log.info("衣橱条目补写模特/原始照片: wardrobeId={}, recordId={}",
                        existed.getId(), dto.getRecordId());
            }
            return BeanUtils.copyBean(existed, WardrobeDTO.class);
        }
        // 二次校验：UserContext 中的 userId 与 dto.userId 应一致（透传 user-info 头）
        Long contextUserId = UserContext.getUser();
        if (contextUserId != null && !contextUserId.equals(dto.getUserId())) {
            throw new BadRequestException("userId 与登录用户身份不匹配");
        }
        Wardrobe wardrobe = BeanUtils.copyBean(dto, Wardrobe.class);
        wardrobe.setId(null);
        wardrobe.setIsActive(1);
        // type=4 不使用 photo_url/item_id/category/color/style_tags/scene_desc
        wardrobe.setPhotoUrl(null);
        wardrobe.setItemId(null);
        wardrobe.setCategory(null);
        wardrobe.setColor(null);
        wardrobe.setStyleTags(null);
        wardrobe.setSceneDesc(null);
        wardrobeService.save(wardrobe);
        return BeanUtils.copyBean(wardrobe, WardrobeDTO.class);
    }

    @ApiOperation("更新衣橱条目")
    @PutMapping("/{id}")
    public void updateWardrobe(@ApiParam("衣橱条目id") @PathVariable("id") Long id, @RequestBody WardrobeDTO dto) {
        Long userId = UserContext.getUser();
        Wardrobe existing = wardrobeService.getById(id);
        if (existing == null || !existing.getUserId().equals(userId)) {
            throw new BadRequestException("衣橱条目不属于当前登录用户");
        }
        // 更新场景：itemType 未传则沿用现有条目；AI 搭配效果图（itemType=4）允许更新备注等字段，
        // 不执行手动添加校验（避免被 validateItemType 的 type=4 拒绝逻辑拦截）
        if (dto.getItemType() == null) {
            dto.setItemType(existing.getItemType());
        }
        if (dto.getItemType() != 4) {
            validateItemType(dto);
        }
        Wardrobe wardrobe = BeanUtils.copyBean(dto, Wardrobe.class);
        wardrobe.setId(id);
        wardrobe.setUserId(userId);
        wardrobeService.updateById(wardrobe);
    }

    @ApiOperation("删除衣橱条目（软删除）")
    @DeleteMapping("/{id}")
    public void deleteWardrobe(@ApiParam("衣橱条目id") @PathVariable("id") Long id) {
        Long userId = UserContext.getUser();
        Wardrobe existing = wardrobeService.getById(id);
        if (existing == null || !existing.getUserId().equals(userId)) {
            throw new BadRequestException("衣橱条目不属于当前登录用户");
        }
        wardrobeService.lambdaUpdate()
                .eq(Wardrobe::getId, id)
                .eq(Wardrobe::getUserId, userId)
                .set(Wardrobe::getIsActive, 0)
                .update();
    }

    @ApiOperation("按搭配记录删除衣橱条目（用户取消满意/改不满意时联动删除，软删除）")
    @DeleteMapping("/by-record/{recordId}")
    public void deleteWardrobeByRecord(@ApiParam("关联搭配记录ID（ai_outfit_record.id）") @PathVariable("recordId") Long recordId) {
        Long userId = UserContext.getUser();
        wardrobeService.lambdaUpdate()
                .eq(Wardrobe::getRecordId, recordId)
                .eq(Wardrobe::getUserId, userId)
                .eq(Wardrobe::getIsActive, 1)
                .set(Wardrobe::getIsActive, 0)
                .update();
    }

    @ApiOperation("查询当前用户衣橱中所有 item_id 列表（用于排除已加衣橱的商品）")
    @GetMapping("/my-item-ids")
    public List<Long> queryMyWardrobeItemIds(
            @ApiParam("用户ID（服务间调用时显式传入；用户端调用可不传，自动从 UserContext 获取）")
            @RequestParam(value = "userId", required = false) Long userId) {
        // P1-9 修复：同时支持 UserContext 用户端调用和服务间显式 userId 调用（对齐 CartController 模式）
        Long targetUserId = userId != null ? userId : UserContext.getUser();
        if (targetUserId == null) {
            return CollUtils.emptyList();
        }
        List<Wardrobe> list = wardrobeService.lambdaQuery()
                .eq(Wardrobe::getUserId, targetUserId)
                .eq(Wardrobe::getIsActive, 1)
                .isNotNull(Wardrobe::getItemId)
                .ne(Wardrobe::getItemId, 0L)
                .list();
        if (CollUtils.isEmpty(list)) {
            return CollUtils.emptyList();
        }
        return list.stream()
                .map(Wardrobe::getItemId)
                .filter(itemId -> itemId != null)
                .distinct()
                .collect(Collectors.toList());
    }

    /**
     * 校验 item_type 与 item_id/photo_url 的匹配关系（用户端 POST /wardrobe 入口）
     * type=1 必有 item_id；type=2/3 必有 photo_url；type=4 不允许用户端调用（仅 /wardrobe/internal）
     */
    private void validateItemType(WardrobeDTO dto) {
        if (dto == null || dto.getItemType() == null) {
            throw new BadRequestException("条目类型 item_type 不能为空");
        }
        Integer itemType = dto.getItemType();
        if (itemType == 1) {
            if (dto.getItemId() == null) {
                throw new BadRequestException("单品模式（item_type=1）必须提供 item_id");
            }
        } else if (itemType == 2 || itemType == 3) {
            if (dto.getPhotoUrl() == null || dto.getPhotoUrl().isEmpty()) {
                throw new BadRequestException("自定义上传/全身自拍（item_type=" + itemType + "）必须提供 photo_url");
            }
        } else if (itemType == 4) {
            // v3.1：item_type=4 仅服务间调用 /wardrobe/internal 写入，用户端 POST /wardrobe 拒绝
            throw new BadRequestException("item_type=4（AI 搭配效果图）不支持手动添加，由系统自动入库");
        } else {
            throw new BadRequestException("非法的条目类型 item_type=" + itemType);
        }
    }
}
