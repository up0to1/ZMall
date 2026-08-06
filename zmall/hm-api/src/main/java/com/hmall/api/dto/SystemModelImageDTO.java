package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.Size;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 系统模特图 DTO（全平台共用的统一模特图池）
 *
 * <p>2026-07-19 重构：合并原 ShopModelImageDTO + PlatformModelImageDTO 为统一 DTO。
 *
 * <p>权限规则：
 * <ul>
 *   <li>查询：所有登录商家都能查 is_active=1 的</li>
 *   <li>新增：任何商家都能上传新模特图（上传即入池）</li>
 *   <li>修改/删除：仅 uploaderUserId == 当前用户 可操作</li>
 * </ul>
 *
 * <p>用于：
 * <ul>
 *   <li>AI 模特功能：商家选 modelImageId 提交生成任务</li>
 *   <li>AI 随心搭：用户无自拍照时用默认模特图（is_default=1 优先）</li>
 * </ul>
 */
@ApiModel(description = "系统模特图（全平台共用）")
@Data
public class SystemModelImageDTO {

    @ApiModelProperty("主键ID")
    private Long id;

    @ApiModelProperty("模特图 URL（相对路径或完整 URL，创建时由后端填充，update 时可不传）")
    @Size(max = 512, message = "模特图URL最长 512 字符")
    private String imageUrl;

    @ApiModelProperty("上传者用户ID（仅创建者可修改/删除）")
    private Long uploaderUserId;

    @ApiModelProperty("性别: male/female")
    private String gender;

    @ApiModelProperty("肤色: fair/wheat/dark")
    private String skinTone;

    @ApiModelProperty("身高（cm），150-200")
    private Integer height;

    @ApiModelProperty("体重（kg），35-120")
    private Integer weight;

    @ApiModelProperty("年龄段: 18-25 / 26-35 / 36-45 / 46+")
    private String ageRange;

    @ApiModelProperty("体型: slim/standard/curvy/plus")
    private String bodyType;

    @ApiModelProperty("风格标签（如 通勤/休闲/约会/运动/商务/街头/复古/欧美/亚洲）")
    private List<String> styleTags;

    @ApiModelProperty("备注（≤50字）")
    private String note;

    @ApiModelProperty("是否系统推荐默认图")
    private Boolean isDefault = false;

    @ApiModelProperty("来源: 0=商家上传 1=AI模特任务后保存 2=平台运营 3=AI自动生成")
    private Integer source = 0;

    @ApiModelProperty("是否启用（软删标记）：1=启用 0=下架")
    private Integer isActive = 1;

    @ApiModelProperty("是否为当前用户上传（用于前端判断能否编辑/删除）")
    private Boolean mine = false;

    @ApiModelProperty("创建时间")
    private LocalDateTime createdAt;

    @ApiModelProperty("更新时间")
    private LocalDateTime updatedAt;
}
