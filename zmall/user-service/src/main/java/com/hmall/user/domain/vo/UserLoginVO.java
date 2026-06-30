package com.hmall.user.domain.vo;

import lombok.Data;

@Data
public class UserLoginVO {
    private String token;
    private Long id;
    private Long userId;
    private String username;
    private Integer balance;
    private Integer role;
    private String phone;
}
