package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * AI 配额预扣结果
 */
@ApiModel(description = "AI 配额预扣结果")
@Data
@NoArgsConstructor
@AllArgsConstructor
public class QuotaResultDTO {

    @ApiModelProperty(value = "是否成功")
    private Boolean success;

    @ApiModelProperty(value = "扣减来源: free-免费额度 / paid-付费余额 / refused-拒绝")
    private String source;

    @ApiModelProperty(value = "提示信息")
    private String msg;

    public static QuotaResultDTO success(String source) {
        return new QuotaResultDTO(true, source, "预扣成功");
    }

    public static QuotaResultDTO refused() {
        return new QuotaResultDTO(false, "refused", "AI 生成次数或余额不足");
    }
}
