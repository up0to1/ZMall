package com.hmall.item.service;

import com.hmall.api.dto.AiModelStatsDTO;
import com.hmall.api.dto.AiRatingDistDTO;
import com.hmall.api.dto.AiTaskTrendDTO;

import java.util.List;

/**
 * AI 数据看板服务（商家端，阶段一：AI 模特图指标）
 *
 * <p>所有方法默认从 {@code UserContext.getUser()} 获取当前商家 shopId，
 * 分别聚合 ai_task 表（task_type=MODEL）和 ai_model_image_feedback 表。
 */
public interface IAiStatsService {

    /**
     * 商家维度 AI 模特图统计概览
     */
    AiModelStatsDTO getOverview();

    /**
     * 近 N 天任务趋势（按天聚合，日期升序）
     *
     * @param days 天数（外部已限制 1-90）
     */
    List<AiTaskTrendDTO> getTrend(int days);

    /**
     * 评分分布（1-5 星，缺省星级补 0）
     */
    List<AiRatingDistDTO> getRatingDist();
}
