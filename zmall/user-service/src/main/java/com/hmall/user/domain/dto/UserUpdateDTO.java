package com.hmall.user.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

@Data
@ApiModel(description = "用户信息更新实体")
public class UserUpdateDTO {

    @ApiModelProperty("手机号")
    private String phone;
}
