package com.hmall.api.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class DeductMoneyDTO {
    private String pw;
    private Integer amount;
}
