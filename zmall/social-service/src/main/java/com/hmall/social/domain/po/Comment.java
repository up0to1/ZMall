package com.hmall.social.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@Accessors(chain = true)
@TableName("comment")
public class Comment implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    private Long itemId;

    private Long orderId;

    private Long userId;

    private String content;

    private Integer rating;

    private String images;

    private String reply;

    private LocalDateTime replyTime;

    private Integer isHidden;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}