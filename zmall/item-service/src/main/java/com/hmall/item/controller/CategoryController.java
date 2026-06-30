package com.hmall.item.controller;

import com.hmall.common.utils.BeanUtils;
import com.hmall.item.domain.po.Category;
import com.hmall.item.service.ICategoryService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Api(tags = "商品分类管理接口")
@RestController
@RequestMapping("/categories")
@RequiredArgsConstructor
public class CategoryController {

    private final ICategoryService categoryService;

    @ApiOperation("查询所有分类")
    @GetMapping
    public List<Category> queryAllCategories() {
        return categoryService.list();
    }

    @ApiOperation("新增分类")
    @PostMapping
    public void saveCategory(@RequestBody Category category) {
        categoryService.save(category);
    }

    @ApiOperation("更新分类")
    @PutMapping("/{id}")
    public void updateCategory(@PathVariable("id") Long id, @RequestBody Category category) {
        category.setId(id);
        categoryService.updateById(category);
    }

    @ApiOperation("删除分类")
    @DeleteMapping("/{id}")
    public void deleteCategory(@PathVariable("id") Long id) {
        categoryService.removeById(id);
    }
}
