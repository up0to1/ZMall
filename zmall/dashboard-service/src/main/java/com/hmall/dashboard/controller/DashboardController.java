package com.hmall.dashboard.controller;

import com.hmall.api.dto.SalesTrendDTO;
import com.hmall.api.dto.TopItemDTO;
import com.hmall.dashboard.domain.dto.DashboardDTO;
import com.hmall.dashboard.domain.dto.SeckillStatsDTO;
import com.hmall.dashboard.service.DashboardService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Api(tags = "商家后台-数据仪表盘")
@RestController
@RequestMapping("/merchant/dashboard")
@RequiredArgsConstructor
public class DashboardController {

    private final DashboardService dashboardService;

    @ApiOperation("今日概览")
    @GetMapping("/today")
    public DashboardDTO getTodayOverview() {
        return dashboardService.getTodayOverview();
    }

    @ApiOperation("销售趋势")
    @GetMapping("/sales")
    public List<SalesTrendDTO> getSalesTrend(@RequestParam(value = "days", defaultValue = "7") int days) {
        return dashboardService.getSalesTrend(days);
    }

    @ApiOperation("商品销量排行")
    @GetMapping("/top-items")
    public List<TopItemDTO> getTopItems(@RequestParam(value = "limit", defaultValue = "10") int limit) {
        return dashboardService.getTopItems(limit);
    }

    @ApiOperation("秒杀活动数据")
    @GetMapping("/seckill")
    public List<SeckillStatsDTO> getSeckillStats() {
        return dashboardService.getSeckillStats();
    }
}
