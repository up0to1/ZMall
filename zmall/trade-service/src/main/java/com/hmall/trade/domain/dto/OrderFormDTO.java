package com.hmall.trade.domain.dto;

import com.hmall.api.dto.OrderDetailDTO;
import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

@Data
@ApiModel(description = "交易下单表单实体")
public class OrderFormDTO {
    @ApiModelProperty("收货地址id")
    private Long addressId;
    @ApiModelProperty("支付类型")
    private Integer paymentType;
    @ApiModelProperty("下单商品列表")
    private List<OrderDetailDTO> details;
    @ApiModelProperty("使用的优惠券ID，不使用优惠券时不传")
    private Long couponId;
    @ApiModelProperty("AI 随心搭搭配记录ID（立即下单流程携带；为空表示非 AI 搭配下单，2026-08-06 新增）")
    private Long outfitRecordId;
    @ApiModelProperty("AI 随心搭任务ID（outfitRecordId 缺失时按 taskId+outfitIndex 定位搭配记录）")
    private String outfitTaskId;
    @ApiModelProperty("AI 随心搭搭配索引（outfitRecordId 缺失时使用，0/1/2）")
    private Integer outfitIndex;
}
