package com.hmall.item.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.item.domain.po.Category;
import com.hmall.item.mapper.CategoryMapper;
import com.hmall.item.service.ICategoryService;
import org.springframework.stereotype.Service;

@Service
public class CategoryServiceImpl extends ServiceImpl<CategoryMapper, Category> implements ICategoryService {
}
