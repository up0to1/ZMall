package com.hmall.user.controller;

import com.hmall.common.domain.PageDTO;
import com.hmall.user.domain.dto.BatchDeleteDTO;
import com.hmall.user.domain.dto.RecordViewDTO;
import com.hmall.user.domain.vo.UserBrowseHistoryVO;
import com.hmall.user.service.IUserBrowseHistoryService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

/**
 * 用户浏览记录
 * <p>记录/查询/删除浏览记录，前端在商品详情页加载后埋点上报
 */
@Api(tags = "用户浏览记录接口")
@RestController
@RequestMapping("/browse-history")
@RequiredArgsConstructor
public class UserBrowseHistoryController {

    private final IUserBrowseHistoryService browseHistoryService;

    @ApiOperation("分页查询我的浏览记录")
    @GetMapping("/page")
    public PageDTO<UserBrowseHistoryVO> queryMyHistory(
            @RequestParam(value = "pageNo", defaultValue = "1") Integer pageNo,
            @RequestParam(value = "pageSize", defaultValue = "20") Integer pageSize) {
        return browseHistoryService.queryMyHistory(pageNo, pageSize);
    }

    @ApiOperation("记录一次浏览（同一商品已存在则累计次数）")
    @PostMapping
    public void recordView(@RequestBody RecordViewDTO dto) {
        browseHistoryService.recordView(dto.getItemId(), dto.getViewSource(), dto.getViewDuration());
    }

    @ApiOperation("删除单条浏览记录")
    @DeleteMapping("/{id}")
    public void deleteById(@PathVariable("id") Long id) {
        browseHistoryService.deleteById(id);
    }

    @ApiOperation("批量删除浏览记录")
    @DeleteMapping("/batch")
    public void deleteBatch(@RequestBody BatchDeleteDTO dto) {
        browseHistoryService.deleteBatch(dto.getIds());
    }

    @ApiOperation("清空所有浏览记录")
    @DeleteMapping("/clear")
    public void clearAll() {
        browseHistoryService.clearAll();
    }
}
