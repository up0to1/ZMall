package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "粉丝统计")
public class FansStatsDTO {
    @ApiModelProperty("粉丝总数")
    private Long totalFans;
    @ApiModelProperty("今日新增")
    private Long todayNew;
    @ApiModelProperty("本周新增")
    private Long weekNew;
    @ApiModelProperty("活跃粉丝")
    private Long activeFans;
}