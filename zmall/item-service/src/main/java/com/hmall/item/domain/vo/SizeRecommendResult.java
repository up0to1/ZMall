package com.hmall.item.domain.vo;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.Data;

import java.util.List;

/**
 * 尺码推荐结果
 *
 * @author hmall
 * @since 2026-07-27
 */
@Data
@ApiModel(description = "尺码推荐结果")
public class SizeRecommendResult {

    @ApiModelProperty("推荐尺码")
    private String recommendedSize;

    @ApiModelProperty("匹配置信度（0-1）")
    private Double confidence;

    @ApiModelProperty("备选尺码列表（按置信度降序）")
    private List<AlternativeSize> alternatives;

    @ApiModelProperty("推荐理由")
    private String reason;

    @Data
    @ApiModel(description = "备选尺码")
    public static class AlternativeSize {
        @ApiModelProperty("尺码标签")
        private String size;

        @ApiModelProperty("匹配置信度（0-1）")
        private Double confidence;

        public AlternativeSize(String size, Double confidence) {
            this.size = size;
            this.confidence = confidence;
        }
    }
}
