package com.hmall.user.controller;

import com.hmall.api.dto.BodyProfileDTO;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.CollUtils;
import com.hmall.common.utils.UserContext;
import com.hmall.user.domain.po.BodyProfile;
import com.hmall.user.service.IBodyProfileService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import io.swagger.annotations.ApiParam;
import lombok.RequiredArgsConstructor;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * <p>
 * 用户身体信息档案 前端控制器
 * </p>
 *
 * <p>2026-07-27 新增：支持用户登记多个身体信息档案（适配身材变化），
 * AI 搭配时用户可选中档案，系统据此做尺码推荐。
 *
 * <p>字段按品类需求设计：
 * <ul>
 *   <li>上衣/外套：身高、体重、胸围、肩宽</li>
 *   <li>下装/裤子：身高、腰围、臀围</li>
 *   <li>鞋子：脚长、脚宽</li>
 *   <li>帽子：头围（可选）</li>
 * </ul>
 *
 * @author hmall
 * @since 2026-07-27
 */
@RestController
@RequestMapping("/body-profile")
@RequiredArgsConstructor
@Api(tags = "用户身体信息档案接口")
public class BodyProfileController {

    private final IBodyProfileService bodyProfileService;

    @ApiOperation("查询当前用户身体信息档案列表")
    @GetMapping
    public List<BodyProfileDTO> findMyBodyProfiles() {
        Long userId = UserContext.getUser();
        List<BodyProfile> list = bodyProfileService.lambdaQuery()
                .eq(BodyProfile::getUserId, userId)
                .eq(BodyProfile::getIsActive, 1)
                .orderByDesc(BodyProfile::getIsDefault)
                .orderByDesc(BodyProfile::getCreateTime)
                .list();
        if (CollUtils.isEmpty(list)) {
            return CollUtils.emptyList();
        }
        return BeanUtils.copyList(list, BodyProfileDTO.class);
    }

    @ApiOperation("服务间调用-查询指定用户身体信息档案列表（内部接口，网关拦截外部访问）")
    @GetMapping("/internal/list")
    public List<BodyProfileDTO> queryUserBodyProfiles(@ApiParam("用户ID") @RequestParam("userId") Long userId) {
        if (userId == null) {
            return CollUtils.emptyList();
        }
        List<BodyProfile> list = bodyProfileService.lambdaQuery()
                .eq(BodyProfile::getUserId, userId)
                .eq(BodyProfile::getIsActive, 1)
                .orderByDesc(BodyProfile::getIsDefault)
                .orderByDesc(BodyProfile::getCreateTime)
                .list();
        if (CollUtils.isEmpty(list)) {
            return CollUtils.emptyList();
        }
        return BeanUtils.copyList(list, BodyProfileDTO.class);
    }

    @ApiOperation("查询单个身体信息档案（归属校验：仅档案所有者或服务间调用可访问）")
    @GetMapping("/{id}")
    public BodyProfileDTO queryBodyProfile(@ApiParam("档案ID") @PathVariable("id") Long id) {
        BodyProfile profile = bodyProfileService.getById(id);
        if (profile == null || profile.getIsActive() == null || profile.getIsActive() == 0) {
            return null;
        }
        // IDOR 越权修复（2026-07-27）：校验档案归属
        // 优先用 UserContext.getUser() 判断（外部请求经网关带 user-info header）；
        // 服务间调用（如 ai-outfit 通过 Feign 调用）header 中 user-info 可能为空，
        // 此时通过 Feign 客户端已传 userId 参数的接口（/list?userId=）走另一条路径，
        // 本接口对外部请求必须校验归属。
        Long currentUserId = UserContext.getUser();
        if (currentUserId != null && !currentUserId.equals(profile.getUserId())) {
            throw new BadRequestException("身体信息档案不属于当前登录用户");
        }
        return BeanUtils.copyBean(profile, BodyProfileDTO.class);
    }

    @ApiOperation("新增身体信息档案")
    @PostMapping
    @Transactional(rollbackFor = Exception.class)
    public void addBodyProfile(@RequestBody BodyProfileDTO dto) {
        Long userId = UserContext.getUser();
        validateBodyProfile(dto);
        BodyProfile profile = BeanUtils.copyBean(dto, BodyProfile.class);
        profile.setId(null);
        profile.setUserId(userId);
        profile.setIsActive(1);
        // 若设为默认，先清除其他默认档案
        if (Integer.valueOf(1).equals(profile.getIsDefault())) {
            bodyProfileService.lambdaUpdate()
                    .eq(BodyProfile::getUserId, userId)
                    .set(BodyProfile::getIsDefault, 0)
                    .update();
        }
        bodyProfileService.save(profile);
    }

    @ApiOperation("更新身体信息档案")
    @PutMapping("/{id}")
    @Transactional(rollbackFor = Exception.class)
    public void updateBodyProfile(@ApiParam("档案ID") @PathVariable("id") Long id, @RequestBody BodyProfileDTO dto) {
        Long userId = UserContext.getUser();
        BodyProfile existing = bodyProfileService.getById(id);
        if (existing == null || !existing.getUserId().equals(userId)) {
            throw new BadRequestException("身体信息档案不属于当前登录用户");
        }
        validateBodyProfile(dto);
        BodyProfile profile = BeanUtils.copyBean(dto, BodyProfile.class);
        profile.setId(id);
        profile.setUserId(userId);
        // 若设为默认，先清除其他默认档案
        if (Integer.valueOf(1).equals(profile.getIsDefault())) {
            bodyProfileService.lambdaUpdate()
                    .eq(BodyProfile::getUserId, userId)
                    .ne(BodyProfile::getId, id)
                    .set(BodyProfile::getIsDefault, 0)
                    .update();
        }
        bodyProfileService.updateById(profile);
    }

    @ApiOperation("删除身体信息档案（软删除）")
    @DeleteMapping("/{id}")
    public void deleteBodyProfile(@ApiParam("档案ID") @PathVariable("id") Long id) {
        Long userId = UserContext.getUser();
        BodyProfile existing = bodyProfileService.getById(id);
        if (existing == null || !existing.getUserId().equals(userId)) {
            throw new BadRequestException("身体信息档案不属于当前登录用户");
        }
        bodyProfileService.lambdaUpdate()
                .eq(BodyProfile::getId, id)
                .eq(BodyProfile::getUserId, userId)
                .set(BodyProfile::getIsActive, 0)
                .update();
    }

    @ApiOperation("设置默认身体信息档案")
    @PutMapping("/{id}/default")
    @Transactional(rollbackFor = Exception.class)
    public void setDefaultBodyProfile(@ApiParam("档案ID") @PathVariable("id") Long id) {
        Long userId = UserContext.getUser();
        BodyProfile existing = bodyProfileService.getById(id);
        if (existing == null || !existing.getUserId().equals(userId)) {
            throw new BadRequestException("身体信息档案不属于当前登录用户");
        }
        // 清除其他默认档案
        bodyProfileService.lambdaUpdate()
                .eq(BodyProfile::getUserId, userId)
                .set(BodyProfile::getIsDefault, 0)
                .update();
        // 设置当前档案为默认
        bodyProfileService.lambdaUpdate()
                .eq(BodyProfile::getId, id)
                .eq(BodyProfile::getUserId, userId)
                .set(BodyProfile::getIsDefault, 1)
                .update();
    }

    /**
     * 校验身体信息档案必填字段
     */
    private void validateBodyProfile(BodyProfileDTO dto) {
        if (dto == null) {
            throw new BadRequestException("身体信息档案不能为空");
        }
        if (dto.getProfileName() == null || dto.getProfileName().isEmpty()) {
            throw new BadRequestException("档案名称（profileName）不能为空");
        }
        if (dto.getGender() == null || dto.getGender().isEmpty()) {
            throw new BadRequestException("性别（gender）不能为空");
        }
        if (!"male".equals(dto.getGender()) && !"female".equals(dto.getGender())) {
            throw new BadRequestException("性别（gender）必须为 male 或 female");
        }
    }
}
