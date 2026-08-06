package com.hmall.api.dto;

import io.swagger.annotations.ApiModel;
import io.swagger.annotations.ApiModelProperty;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@Data
@ApiModel(description = "我的衣橱实体")
@NoArgsConstructor
@AllArgsConstructor
public class WardrobeDTO {
    @ApiModelProperty("衣橱条目id")
    private Long id;
    @ApiModelProperty("用户ID")
    private Long userId;
    @ApiModelProperty("条目类型：1=单品模式 2=自定义上传 3=全身自拍 4=AI搭配效果图（v3.1 新增）")
    private Integer itemType;
    @ApiModelProperty("商品ID（item_type=1 时关联商品，可空）")
    private Long itemId;
    @ApiModelProperty("图片URL（item_type=2/3 时 OSS URL，可空）")
    private String photoUrl;
    @ApiModelProperty("AI 穿搭效果图 URL（item_type=4 时非空；v3.1 新增）")
    private String outfitResultUrl;
    @ApiModelProperty("用户原自拍照 URL（item_type=4 时可空；v3.1 新增）")
    private String originalPhotoUrl;
    @ApiModelProperty("AI 搭配单品详情 JSON 字符串（item_type=4 时非空；v3.1 新增）")
    private String outfitJson;
    @ApiModelProperty("关联 ai_outfit_record.id（item_type=4 时非空；v3.1 新增）")
    private Long recordId;
    @ApiModelProperty("中文品类（可空）")
    private String category;
    @ApiModelProperty("中文颜色（可空）")
    private String color;
    @ApiModelProperty("风格标签 JSON 数组字符串，如 [\"通勤\",\"简约\"]（可空）")
    private String styleTags;
    @ApiModelProperty("场景标注（可空）")
    private String sceneDesc;
    @ApiModelProperty("是否有效：1有效 0已删除")
    private Integer isActive;
}
