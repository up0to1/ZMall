package com.hmall.api.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "粉丝视图")
public class FansVO {
    @ApiModelProperty("用户ID")
    private Long userId;
    @ApiModelProperty("关注时间")
    private String createTime;
}
