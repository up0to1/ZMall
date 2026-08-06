package com.hmall.item.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.math.BigDecimal;

/**
 * 身体信息简化 DTO（用于尺码推荐请求）
 *
 * <p>与 com.hmall.api.dto.BodyProfileDTO 字段一致，但不含 id/userId/isDefault 等管理字段，
 * 仅保留尺码推荐所需的身体测量字段。
 *
 * @author hmall
 * @since 2026-07-27
 */
@Data
@ApiModel(description = "身体信息（尺码推荐用）")
public class BodyProfileSimpleDTO {
    @ApiModelProperty("性别：male/female")
    private String gender;
    @ApiModelProperty("身高(cm)")
    private Integer height;
    @ApiModelProperty("体重(kg)")
    private BigDecimal weight;
    @ApiModelProperty("肩宽(cm)")
    private BigDecimal shoulderWidth;
    @ApiModelProperty("胸围(cm)")
    private BigDecimal bust;
    @ApiModelProperty("腰围(cm)")
    private BigDecimal waist;
    @ApiModelProperty("臀围(cm)")
    private BigDecimal hip;
    @ApiModelProperty("脚长(cm)")
    private BigDecimal footLength;
    @ApiModelProperty("脚宽(cm)")
    private BigDecimal footWidth;
    @ApiModelProperty("头围(cm)")
    private BigDecimal headCircumference;
}
