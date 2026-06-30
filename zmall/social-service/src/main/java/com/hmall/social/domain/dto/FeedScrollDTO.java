package com.hmall.social.domain.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
@ApiModel(description = "Feed流滚动分页响应")
public class FeedScrollDTO<T> {
    @ApiModelProperty("数据列表")
    private List<T> list;
    @ApiModelProperty("总条数")
    private Long total;
    @ApiModelProperty("当前页最后一条的score，用于请求下一页")
    private Double lastScore;
    @ApiModelProperty("当前页第一条的score，用于请求上一页")
    private Double firstScore;
    @ApiModelProperty("是否有下一页")
    private Boolean hasNext;
    @ApiModelProperty("是否有上一页")
    private Boolean hasPrev;
}
