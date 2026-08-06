package com.hmall.item.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import javax.validation.constraints.NotEmpty;
import javax.validation.constraints.NotNull;
import java.util.List;

/**
 * 批量尺码推荐请求（搭配选购场景）
 *
 * <p>用户查看 AI 搭配的多件单品时，一次性获取每件单品的推荐尺码。
 *
 * <p>2026-07-27 改造：原含 category 字段，现仅需 itemId（recommendSizeByItem 内部
 * 会按 itemId 三级回退查询商品对应尺码表，自动获取 category）。
 *
 * @author hmall
 * @since 2026-07-27
 */
@Data
@ApiModel(description = "批量尺码推荐请求")
public class SizeRecommendBatchRequest {

    @NotNull(message = "身体信息不能为空")
    @ApiModelProperty("用户身体信息")
    private BodyProfileSimpleDTO bodyProfile;

    @NotEmpty(message = "商品ID列表不能为空")
    @ApiModelProperty("商品ID列表")
    private List<Long> itemIds;
}
