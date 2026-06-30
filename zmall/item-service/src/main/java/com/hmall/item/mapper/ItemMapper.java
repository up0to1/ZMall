package com.hmall.item.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.hmall.api.dto.OrderDetailDTO;
import com.hmall.item.domain.po.Item;
import org.apache.ibatis.annotations.Update;

/**
 * <p>
 * 商品表 Mapper 接口
 * </p>
 *
 * @author 虎哥
 * @since 2023-05-05
 */
public interface ItemMapper extends BaseMapper<Item> {

    @Update("UPDATE item SET stock = stock - #{num} WHERE id = #{itemId} AND stock >= #{num}")
    int updateStock(OrderDetailDTO orderDetail);

    @Update("UPDATE item SET stock = stock + #{num} WHERE id = #{itemId}")
    int restoreStock(OrderDetailDTO orderDetail);
}
