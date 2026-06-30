package com.hmall.trade.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@Accessors(chain = true)
@TableName("coupon")
public class Coupon implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.ASSIGN_ID)
    private Long id;

    private String name;

    /** 优惠方式：1-满减券 2-折扣券 */
    private Integer type;

    /** 券类别：1-普通券 2-秒杀券 */
    private Integer couponType;

    /** 满减时为减免金额(分)，折扣时为折扣率(如85=8.5折) */
    private Integer discountValue;

    /** 使用门槛金额(分) */
    private Integer thresholdAmount;

    /** 购买价格(分)，0表示免费领取 */
    private Integer purchasePrice;

    /** 适用范围：1-全部商品 2-部分商品 */
    private Integer scopeType;

    /** 领取后有效天数，NULL表示永久有效 */
    private Integer validDays;

    private Integer totalCount;

    private Integer receivedCount;

    private Integer usedCount;

    private Integer perUserLimit;

    /** 优惠期开始时间（有效期开始） */
    private LocalDateTime beginTime;

    /** 优惠期结束时间（有效期结束） */
    private LocalDateTime endTime;

    /** 1-上架 0-下架 */
    private Integer status;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
