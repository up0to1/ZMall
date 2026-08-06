package com.hmall.user.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;
import lombok.experimental.Accessors;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 用户浏览记录
 */
@Data
@Accessors(chain = true)
@TableName("user_browse_history")
public class UserBrowseHistory implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "id", type = IdType.AUTO)
    private Long id;

    private Long userId;

    private Long itemId;

    private Long shopId;

    private String category;

    /**
     * 停留时长（秒）
     */
    private Integer viewDuration;

    /**
     * 浏览来源：search/recommend/ai_outfit/shop/direct
     */
    private String viewSource;

    /**
     * 累计浏览次数
     */
    private Integer viewCount;

    /**
     * 最后浏览时间
     */
    private LocalDateTime lastViewedAt;

    /**
     * 首次浏览时间
     */
    private LocalDateTime createdAt;

    @TableField(value = "updated_at", update = "now()")
    private LocalDateTime updatedAt;
}
