package com.hmall.trade.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;

/**
 * 优惠券-商品关联表
 * 当优惠券scope_type=2（部分商品）时，通过此表确定优惠券可用的商品
 */
@Data
@Accessors(chain = true)
@TableName("coupon_item")
public class CouponItem implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    /** 优惠券ID */
    private Long couponId;

    /** 商品ID */
    private Long itemId;
}
