package com.hmall.trade.domain.po;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

@Data
@TableName("seckill_item")
public class SeckillItem implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableId(value = "item_id", type = IdType.INPUT)
    private Long itemId;

    private Integer seckillStock;

    private Integer seckillPrice;

    private Integer maxPerUser;

    /** 开抢时间 */
    private LocalDateTime rushBeginTime;

    /** 抢购结束时间 */
    private LocalDateTime rushEndTime;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;
}
