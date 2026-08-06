package com.hmall.user.domain.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户浏览记录展示 VO
 * <p>商品展示信息（itemName/itemImage/itemPrice/shopName）通过 Feign 调 item-service 拉取填充
 */
@Data
@ApiModel(description = "用户浏览记录展示对象")
public class UserBrowseHistoryVO {

    @ApiModelProperty("浏览记录主键ID")
    private Long id;

    @ApiModelProperty("商品ID")
    private Long itemId;

    @ApiModelProperty("商品名称")
    private String itemName;

    @ApiModelProperty("商品主图")
    private String itemImage;

    @ApiModelProperty("商品价格（分）")
    private Integer itemPrice;

    @ApiModelProperty("店铺ID（商家用户ID）")
    private Long shopId;

    @ApiModelProperty("店铺名称")
    private String shopName;

    @ApiModelProperty("商品品类")
    private String category;

    @ApiModelProperty("累计浏览次数")
    private Integer viewCount;

    @ApiModelProperty("本次浏览来源")
    private String viewSource;

    @ApiModelProperty("最后浏览时间")
    private LocalDateTime lastViewedAt;

    @ApiModelProperty("首次浏览时间")
    private LocalDateTime createdAt;
}
