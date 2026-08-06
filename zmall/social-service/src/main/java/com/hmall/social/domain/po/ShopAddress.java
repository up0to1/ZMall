package com.hmall.social.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 商家发货地址
 */
@Data
@Accessors(chain = true)
@TableName("shop_address")
public class ShopAddress implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 商家ID（对应 shop.id） */
    private Long shopId;

    /** 商家用户ID（冗余，便于归属校验） */
    private Long userId;

    private String province;

    private String city;

    private String town;

    private String street;

    private String contact;

    private String mobile;

    /** 是否当前发货地址 1是 0否 */
    private Integer isDefault;

    private String notes;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
