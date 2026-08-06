package com.hmall.item.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.hmall.api.dto.AiModelStatsDTO;
import com.hmall.api.dto.AiRatingDistDTO;
import com.hmall.api.dto.AiTaskTrendDTO;
import com.hmall.common.utils.UserContext;
import com.hmall.item.domain.po.AiModelImageFeedback;
import com.hmall.item.domain.po.AiTask;
import com.hmall.item.mapper.AiModelImageFeedbackMapper;
import com.hmall.item.mapper.AiTaskMapper;
import com.hmall.item.service.IAiStatsService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * AI 数据看板服务实现（商家端，阶段一：AI 模特图指标）
 *
 * <p>聚合策略：
 * <ul>
 *   <li>ai_task 表：按 shop_id = shopId AND task_type = 'MODEL' 过滤</li>
 *   <li>ai_model_image_feedback 表：按 shop_id = shopId 过滤</li>
 *   <li>聚合查询使用 QueryWrapper + selectMaps（项目无 XML mapper，统一用 Wrapper 表达）</li>
 * </ul>
 *
 * <p>注意：ai_task 实际列名为 created_at（PO 中 @TableField("created_at") 显式映射）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AiStatsServiceImpl implements IAiStatsService {

    private final AiTaskMapper aiTaskMapper;
    private final AiModelImageFeedbackMapper aiModelImageFeedbackMapper;

    private static final String TASK_TYPE_MODEL = "MODEL";
    private static final String STATUS_SUCCESS = "SUCCESS";
    private static final String STATUS_PROCESSING = "PROCESSING";
    private static final String STATUS_PENDING = "PENDING";
    private static final String FEEDBACK_TYPE_RATING = "RATING";
    private static final String FEEDBACK_TYPE_REJECT = "REJECT";

    @Override
    public AiModelStatsDTO getOverview() {
        Long shopId = UserContext.getUser();
        AiModelStatsDTO dto = new AiModelStatsDTO();
        if (shopId == null) {
            return dto;
        }

        // ===== ai_task 表统计（shop_id + task_type=MODEL）=====
        LambdaQueryWrapper<AiTask> baseWrapper = new LambdaQueryWrapper<AiTask>()
                .eq(AiTask::getShopId, shopId)
                .eq(AiTask::getTaskType, TASK_TYPE_MODEL);

        long taskTotal = aiTaskMapper.selectCount(baseWrapper);
        dto.setTaskTotal(taskTotal);

        // 今日新增（created_at >= 今日 00:00:00）
        LocalDateTime todayStart = LocalDate.now().atStartOfDay();
        long taskToday = aiTaskMapper.selectCount(new LambdaQueryWrapper<AiTask>()
                .eq(AiTask::getShopId, shopId)
                .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                .ge(AiTask::getCreatedAt, todayStart));
        dto.setTaskToday(taskToday);

        long successCount = aiTaskMapper.selectCount(new LambdaQueryWrapper<AiTask>()
                .eq(AiTask::getShopId, shopId)
                .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                .eq(AiTask::getStatus, STATUS_SUCCESS));
        dto.setSuccessCount(successCount);

        long failedCount = aiTaskMapper.selectCount(new LambdaQueryWrapper<AiTask>()
                .eq(AiTask::getShopId, shopId)
                .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                .in(AiTask::getStatus, "FAILED", "TIMEOUT"));
        dto.setFailedCount(failedCount);

        long processingCount = aiTaskMapper.selectCount(new LambdaQueryWrapper<AiTask>()
                .eq(AiTask::getShopId, shopId)
                .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                .eq(AiTask::getStatus, STATUS_PROCESSING));
        dto.setProcessingCount(processingCount);

        long pendingCount = aiTaskMapper.selectCount(new LambdaQueryWrapper<AiTask>()
                .eq(AiTask::getShopId, shopId)
                .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                .eq(AiTask::getStatus, STATUS_PENDING));
        dto.setPendingCount(pendingCount);

        dto.setSuccessRate(taskTotal > 0 ? (double) successCount / taskTotal : 0.0);

        // 平均耗时（仅成功任务，cost_ms 非空）
        Long avgCostMs = computeAvgCostMs(shopId);
        dto.setAvgCostMs(avgCostMs == null ? 0L : avgCostMs);

        long publishedCount = aiTaskMapper.selectCount(new LambdaQueryWrapper<AiTask>()
                .eq(AiTask::getShopId, shopId)
                .eq(AiTask::getTaskType, TASK_TYPE_MODEL)
                .isNotNull(AiTask::getPublishedItemId));
        dto.setPublishedCount(publishedCount);
        dto.setPublishRate(successCount > 0 ? (double) publishedCount / successCount : 0.0);

        // ===== ai_model_image_feedback 表统计（shop_id）=====
        long ratingCount = aiModelImageFeedbackMapper.selectCount(new LambdaQueryWrapper<AiModelImageFeedback>()
                .eq(AiModelImageFeedback::getShopId, shopId)
                .eq(AiModelImageFeedback::getFeedbackType, FEEDBACK_TYPE_RATING));
        dto.setRatingCount(ratingCount);

        Double avgRating = computeAvgRating(shopId);
        dto.setAvgRating(avgRating == null ? 0.0 : avgRating);

        long rejectCount = aiModelImageFeedbackMapper.selectCount(new LambdaQueryWrapper<AiModelImageFeedback>()
                .eq(AiModelImageFeedback::getShopId, shopId)
                .eq(AiModelImageFeedback::getFeedbackType, FEEDBACK_TYPE_REJECT));
        dto.setRejectCount(rejectCount);

        long denom = ratingCount + rejectCount;
        dto.setRejectRate(denom > 0 ? (double) rejectCount / denom : 0.0);

        long poolCount = aiModelImageFeedbackMapper.selectCount(new LambdaQueryWrapper<AiModelImageFeedback>()
                .eq(AiModelImageFeedback::getShopId, shopId)
                .eq(AiModelImageFeedback::getSavedToPool, 1));
        dto.setPoolCount(poolCount);

        return dto;
    }

    @Override
    public List<AiTaskTrendDTO> getTrend(int days) {
        Long shopId = UserContext.getUser();
        if (shopId == null) {
            return new ArrayList<>();
        }
        // 防御性裁剪：上层已限制 1-90，此处再保底一次
        int safeDays = Math.min(Math.max(days, 1), 90);
        LocalDateTime startDate = LocalDate.now().minusDays(safeDays - 1L).atStartOfDay();

        // 使用 QueryWrapper 表达 DATE(created_at) 分组聚合（项目无 XML mapper）
        QueryWrapper<AiTask> qw = new QueryWrapper<AiTask>()
                .select("DATE(created_at) AS date",
                        "COUNT(*) AS total",
                        "SUM(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END) AS success",
                        "SUM(CASE WHEN status IN ('FAILED','TIMEOUT') THEN 1 ELSE 0 END) AS failed",
                        "AVG(CASE WHEN status='SUCCESS' THEN cost_ms ELSE NULL END) AS avgCostMs")
                .eq("shop_id", shopId)
                .eq("task_type", TASK_TYPE_MODEL)
                .ge("created_at", startDate)
                .groupBy("DATE(created_at)")
                .orderByAsc("date");

        List<Map<String, Object>> rows = aiTaskMapper.selectMaps(qw);
        List<AiTaskTrendDTO> list = new ArrayList<>(rows.size());
        for (Map<String, Object> row : rows) {
            AiTaskTrendDTO dto = new AiTaskTrendDTO();
            dto.setDate(asString(row.get("date")));
            dto.setTotal(asLong(row.get("total")));
            dto.setSuccess(asLong(row.get("success")));
            dto.setFailed(asLong(row.get("failed")));
            dto.setAvgCostMs(asLong(row.get("avgCostMs")));
            list.add(dto);
        }
        return list;
    }

    @Override
    public List<AiRatingDistDTO> getRatingDist() {
        Long shopId = UserContext.getUser();
        if (shopId == null) {
            return buildEmptyRatingDist();
        }

        QueryWrapper<AiModelImageFeedback> qw = new QueryWrapper<AiModelImageFeedback>()
                .select("star_rating", "COUNT(*) AS count")
                .eq("shop_id", shopId)
                .eq("feedback_type", FEEDBACK_TYPE_RATING)
                .groupBy("star_rating")
                .orderByAsc("star_rating");

        List<Map<String, Object>> rows = aiModelImageFeedbackMapper.selectMaps(qw);
        Map<Integer, Long> starToCount = new HashMap<>();
        for (Map<String, Object> row : rows) {
            Integer star = asInt(row.get("star_rating"));
            if (star != null) {
                starToCount.put(star, asLong(row.get("count")));
            }
        }

        // 固定返回 1-5 星，缺省补 0
        List<AiRatingDistDTO> list = new ArrayList<>(5);
        for (int star = 1; star <= 5; star++) {
            AiRatingDistDTO dto = new AiRatingDistDTO();
            dto.setStar(star);
            dto.setCount(starToCount.getOrDefault(star, 0L));
            list.add(dto);
        }
        return list;
    }

    // ============================================================
    // 私有辅助方法
    // ============================================================

    /** 计算成功任务的平均耗时（cost_ms），无成功任务时返回 null */
    private Long computeAvgCostMs(Long shopId) {
        QueryWrapper<AiTask> qw = new QueryWrapper<AiTask>()
                .select("AVG(cost_ms) AS avgCostMs")
                .eq("shop_id", shopId)
                .eq("task_type", TASK_TYPE_MODEL)
                .eq("status", STATUS_SUCCESS);
        List<Map<String, Object>> rows = aiTaskMapper.selectMaps(qw);
        if (rows == null || rows.isEmpty()) {
            return null;
        }
        Object val = rows.get(0).get("avgCostMs");
        if (val == null) {
            return null;
        }
        return Math.round(((Number) val).doubleValue());
    }

    /** 计算平均评分（star_rating），无评分时返回 null */
    private Double computeAvgRating(Long shopId) {
        QueryWrapper<AiModelImageFeedback> qw = new QueryWrapper<AiModelImageFeedback>()
                .select("AVG(star_rating) AS avgRating")
                .eq("shop_id", shopId)
                .eq("feedback_type", FEEDBACK_TYPE_RATING);
        List<Map<String, Object>> rows = aiModelImageFeedbackMapper.selectMaps(qw);
        if (rows == null || rows.isEmpty()) {
            return null;
        }
        Object val = rows.get(0).get("avgRating");
        if (val == null) {
            return null;
        }
        // 保留两位小数
        double v = ((Number) val).doubleValue();
        return Math.round(v * 100.0) / 100.0;
    }

    private List<AiRatingDistDTO> buildEmptyRatingDist() {
        List<AiRatingDistDTO> list = new ArrayList<>(5);
        for (int star = 1; star <= 5; star++) {
            AiRatingDistDTO dto = new AiRatingDistDTO();
            dto.setStar(star);
            dto.setCount(0L);
            list.add(dto);
        }
        return list;
    }

    private String asString(Object val) {
        if (val == null) {
            return null;
        }
        // MySQL DATE() 函数返回 java.sql.Date，转字符串
        if (val instanceof java.sql.Date) {
            return ((java.sql.Date) val).toLocalDate().format(DateTimeFormatter.ISO_LOCAL_DATE);
        }
        return val.toString();
    }

    private long asLong(Object val) {
        if (val == null) {
            return 0L;
        }
        if (val instanceof Number) {
            return ((Number) val).longValue();
        }
        try {
            return Long.parseLong(val.toString());
        } catch (NumberFormatException e) {
            return 0L;
        }
    }

    private Integer asInt(Object val) {
        if (val == null) {
            return null;
        }
        if (val instanceof Number) {
            return ((Number) val).intValue();
        }
        try {
            return Integer.parseInt(val.toString());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
