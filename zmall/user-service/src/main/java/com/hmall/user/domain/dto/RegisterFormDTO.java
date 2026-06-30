package com.hmall.user.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotBlank;
import javax.validation.constraints.Pattern;
import javax.validation.constraints.Size;

@Data
@ApiModel(description = "注册表单实体")
public class RegisterFormDTO {

    @ApiModelProperty(value = "用户名", required = true)
    @NotBlank(message = "用户名不能为空")
    @Size(min = 2, max = 20, message = "用户名长度必须在2-20之间")
    private String username;

    @ApiModelProperty(value = "密码", required = true)
    @NotBlank(message = "密码不能为空")
    @Size(min = 3, max = 20, message = "密码长度必须在3-20之间")
    private String password;

    @ApiModelProperty(value = "手机号", required = false)
    @Pattern(regexp = "^$|1[3-9]\\d{9}$", message = "手机号格式不正确")
    private String phone;

    @ApiModelProperty(value = "注册类型：1-普通用户 2-商家", required = true)
    private Integer role = 1;
}
