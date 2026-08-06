package com.hmall.trade.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * <p>
 * 
 * </p>
 *
 * @author 虎哥
 * @since 2023-05-05
 */
@Data
@EqualsAndHashCode(callSuper = false)
@Accessors(chain = true)
@TableName("order_logistics")
public class OrderLogistics implements Serializable {

    private static final long serialVersionUID = 1L;

    /**
     * 订单id，与订单表一对一
     */
    @TableId(value = "order_id", type = IdType.INPUT)
    private Long orderId;

    /**
     * 物流类型：1=国内快递 2=国际快递 3=专线物流 4=海外仓
     */
    private Integer logisticsType;

    /**
     * 物流单号
     */
    private String logisticsNumber;

    /**
     * 物流公司名称
     */
    private String logisticsCompany;

    /**
     * 物流公司编码（如 SF/DHL/FEDEX，便于API对接）
     */
    private String logisticsCompanyCode;

    /**
     * 物流追踪链接（国际物流常用URL追踪）
     */
    private String trackingUrl;

    /**
     * 发货地址ID（关联 shop_address.id）
     */
    private Long shipFromAddressId;

    /**
     * 发货地文本（冗余，如"广东深圳"/"海外仓-洛杉矶"）
     */
    private String shipFromText;

    /**
     * 目的国（跨境专用，国内为空）
     */
    private String destinationCountry;

    /**
     * 报关价值（单位：分，跨境专用）
     */
    private Integer customsValue;

    /**
     * 包裹重量（单位：克）
     */
    private Integer weight;

    /**
     * 运费（单位：分，商家承担，计入成本）
     */
    private Integer shippingFee;

    /**
     * 收件人
     */
    private String contact;

    /**
     * 收件人手机号码
     */
    private String mobile;

    /**
     * 省
     */
    private String province;

    /**
     * 市
     */
    private String city;

    /**
     * 区
     */
    private String town;

    /**
     * 街道
     */
    private String street;

    /**
     * 创建时间
     */
    private LocalDateTime createTime;

    /**
     * 更新时间
     */
    private LocalDateTime updateTime;


}
