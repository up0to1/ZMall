package com.hmall.item.controller;

import com.hmall.api.dto.AiModelStatsDTO;
import com.hmall.api.dto.AiRatingDistDTO;
import com.hmall.api.dto.AiTaskTrendDTO;
import com.hmall.item.service.IAiStatsService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 商家端 AI 数据看板（阶段一：AI 模特图指标）
 *
 * <p>所有接口需登录态，shopId 从 UserContext.getUser() 获取。
 * 聚合 ai_task 表（task_type=MODEL）与 ai_model_image_feedback 表数据。
 */
@Api(tags = "商家端-AI数据看板")
@RestController
@RequestMapping("/items/admin/ai-stats")
@RequiredArgsConstructor
public class AiStatsController {

    private final IAiStatsService aiStatsService;

    @ApiOperation("AI 模特图统计概览（商家维度）")
    @GetMapping("/overview")
    public AiModelStatsDTO getOverview() {
        return aiStatsService.getOverview();
    }

    @ApiOperation("AI 模特图任务趋势（近 N 天，默认 7 天，最大 90 天）")
    @GetMapping("/trend")
    public List<AiTaskTrendDTO> getTrend(
            @RequestParam(value = "days", defaultValue = "7") int days) {
        // 限制 1-90 天，防御性裁剪
        int safeDays = Math.min(Math.max(days, 1), 90);
        return aiStatsService.getTrend(safeDays);
    }

    @ApiOperation("AI 模特图评分分布（1-5 星）")
    @GetMapping("/rating-dist")
    public List<AiRatingDistDTO> getRatingDist() {
        return aiStatsService.getRatingDist();
    }
}
