package com.hmall.item.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.hmall.item.domain.po.Category;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface CategoryMapper extends BaseMapper<Category> {
}
