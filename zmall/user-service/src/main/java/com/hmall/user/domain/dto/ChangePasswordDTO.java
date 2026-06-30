package com.hmall.user.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Size;

@Data
@ApiModel(description = "修改密码表单")
public class ChangePasswordDTO {

    @ApiModelProperty(value = "原密码", required = true)
    @NotBlank(message = "原密码不能为空")
    private String oldPassword;

    @ApiModelProperty(value = "新密码", required = true)
    @NotBlank(message = "新密码不能为空")
    @Size(min = 6, max = 20, message = "新密码长度必须在6-20之间")
    private String newPassword;
}
