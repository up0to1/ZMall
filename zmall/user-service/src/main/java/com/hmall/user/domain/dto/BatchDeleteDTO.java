package com.hmall.user.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

/**
 * 批量删除请求 DTO
 */
@Data
@ApiModel(description = "批量删除请求参数")
public class BatchDeleteDTO {

    @ApiModelProperty("待删除记录ID列表")
    private List<Long> ids;
}
