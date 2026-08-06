package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * 用户身体信息档案 DTO（跨服务传输用）
 *
 * <p>2026-07-27 新增：用于 user-service ↔ item-service ↔ Python ai-outfit 之间的身体信息传输。
 *
 * @author hmall
 * @since 2026-07-27
 */
@Data
@ApiModel(description = "用户身体信息档案")
@NoArgsConstructor
@AllArgsConstructor
public class BodyProfileDTO {
    @ApiModelProperty("档案ID")
    private Long id;
    @ApiModelProperty("用户ID")
    private Long userId;
    @ApiModelProperty("档案名称（如\"2026年7月身材\"）")
    private String profileName;
    @ApiModelProperty("性别：male/female")
    private String gender;
    @ApiModelProperty("身高(cm) 140-210")
    private Integer height;
    @ApiModelProperty("体重(kg) 35-150")
    private BigDecimal weight;
    @ApiModelProperty("肩宽(cm) 35-55")
    private BigDecimal shoulderWidth;
    @ApiModelProperty("胸围(cm) 70-130")
    private BigDecimal bust;
    @ApiModelProperty("腰围(cm) 50-130")
    private BigDecimal waist;
    @ApiModelProperty("臀围(cm) 70-140")
    private BigDecimal hip;
    @ApiModelProperty("脚长(cm) 20-32")
    private BigDecimal footLength;
    @ApiModelProperty("脚宽(cm) 8-12")
    private BigDecimal footWidth;
    @ApiModelProperty("头围(cm) 50-65")
    private BigDecimal headCircumference;
    @ApiModelProperty("年龄段：18-25/26-35/36-45/46+")
    private String ageRange;
    @ApiModelProperty("体型：slim/standard/curvy/plus")
    private String bodyType;
    @ApiModelProperty("是否默认档案：1=默认 0=普通")
    private Integer isDefault;
    @ApiModelProperty("是否有效：1有效 0已删除")
    private Integer isActive;
    @ApiModelProperty("测量日期")
    private LocalDate measuredAt;
}
