package com.hmall.social.domain.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class ShopFeedMessage {
    private Long feedId;
    private Long shopId;
    private String content;
    private Long createTime;
}