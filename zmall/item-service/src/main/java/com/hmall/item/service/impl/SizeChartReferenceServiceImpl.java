package com.hmall.item.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.api.dto.BodyProfileDTO;
import com.hmall.common.utils.CollUtils;
import com.hmall.item.domain.po.Item;
import com.hmall.item.domain.po.SizeChartReference;
import com.hmall.item.domain.vo.SizeRecommendResult;
import com.hmall.item.mapper.SizeChartReferenceMapper;
import com.hmall.item.service.IItemService;
import com.hmall.item.service.ISizeChartReferenceService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * <p>
 * 尺码对照参考表 服务实现类
 * </p>
 *
 * <p>2026-07-27 改造为店铺维度：
 * <ul>
 *   <li>shop_id = 0  → 系统预置模板（只读，商家可一键复制到自己店铺）</li>
 *   <li>shop_id > 0  → 商家自己维护的尺码表（商家后台 CRUD 管理）</li>
 * </ul>
 *
 * <p>商品与尺码表关联采用方案C（三级回退）：
 * <ol>
 *   <li>商品专用绑定（item.size_chart_id 非空时）</li>
 *   <li>店铺品类通用表（shop_id + category + gender）</li>
 *   <li>系统模板（shop_id = 0 + category + gender）</li>
 * </ol>
 *
 * <p>尺码推荐算法：多维加权匹配
 * <ul>
 *   <li>对每个尺码区间计算匹配度（0-1）</li>
 *   <li>字段匹配分：在区间内=1.0，区间外按距离衰减</li>
 *   <li>总分 = Σ(字段匹配分 × 权重)</li>
 *   <li>返回最高匹配度的尺码</li>
 * </ul>
 *
 * @author hmall
 * @since 2026-07-27
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class SizeChartReferenceServiceImpl
        extends ServiceImpl<SizeChartReferenceMapper, SizeChartReference>
        implements ISizeChartReferenceService {

    /**
     * 系统模板的 shop_id 固定为 0
     */
    private static final Long SYSTEM_TEMPLATE_SHOP_ID = 0L;

    /**
     * 商品查询服务（用于 getItemSizeChart 三级回退时查询 item.creater / category / target_gender）
     */
    private final IItemService itemService;

    /**
     * 各品类的字段权重配置
     */
    private static final Map<String, Map<String, Double>> CATEGORY_WEIGHTS = new HashMap<>();

    static {
        // 上衣/外套：胸围0.4 + 肩宽0.3 + 身高0.2 + 体重0.1
        Map<String, Double> topWeights = new HashMap<>();
        topWeights.put("bust", 0.4);
        topWeights.put("shoulder_width", 0.3);
        topWeights.put("height", 0.2);
        topWeights.put("weight", 0.1);
        CATEGORY_WEIGHTS.put("上衣", topWeights);
        CATEGORY_WEIGHTS.put("外套", new HashMap<>(topWeights));

        // 下装/裤子：腰围0.5 + 臀围0.3 + 身高0.2
        Map<String, Double> bottomWeights = new HashMap<>();
        bottomWeights.put("waist", 0.5);
        bottomWeights.put("hip", 0.3);
        bottomWeights.put("height", 0.2);
        CATEGORY_WEIGHTS.put("下装", bottomWeights);
        CATEGORY_WEIGHTS.put("裤子", new HashMap<>(bottomWeights));

        // 鞋子：脚长0.9 + 脚宽0.1
        Map<String, Double> shoeWeights = new HashMap<>();
        shoeWeights.put("foot_length", 0.9);
        shoeWeights.put("foot_width", 0.1);
        CATEGORY_WEIGHTS.put("鞋", shoeWeights);

        // 帽子：头围1.0
        Map<String, Double> hatWeights = new HashMap<>();
        hatWeights.put("head_circumference", 1.0);
        CATEGORY_WEIGHTS.put("帽子", hatWeights);
    }

    @Override
    public List<SizeChartReference> querySizeChart(String category, String gender) {
        return queryTemplates(category, gender);
    }

    @Override
    public List<SizeChartReference> queryTemplates(String category, String gender) {
        return queryByShopAndCategory(SYSTEM_TEMPLATE_SHOP_ID, category, gender);
    }

    @Override
    public List<SizeChartReference> queryShopSizeChart(Long shopId, String category, String gender) {
        if (shopId == null || shopId <= 0) {
            return CollUtils.emptyList();
        }
        return queryByShopAndCategory(shopId, category, gender);
    }

    @Override
    public List<SizeChartReference> getItemSizeChart(Long itemId) {
        if (itemId == null) {
            return CollUtils.emptyList();
        }
        Item item = itemService.getById(itemId);
        if (item == null) {
            log.warn("[尺码表查询] 商品不存在 itemId={}", itemId);
            return CollUtils.emptyList();
        }

        // 第1级回退：商品专用绑定（item.size_chart_id）
        if (item.getSizeChartId() != null && item.getSizeChartId() > 0) {
            List<SizeChartReference> specificChart = lambdaQuery()
                    .eq(SizeChartReference::getId, item.getSizeChartId())
                    .orderByAsc(SizeChartReference::getSortOrder)
                    .list();
            if (!specificChart.isEmpty()) {
                return specificChart;
            }
            log.warn("[尺码表查询] 商品 {} 显式绑定 size_chart_id={} 但记录不存在，回退到店铺通用", itemId, item.getSizeChartId());
        }

        // 店铺ID = item.creater（项目无独立 shop 概念，商家用户ID即店铺ID）
        Long shopId = item.getCreater();
        String category = item.getCategory();
        String gender = item.getTargetGender();

        // 第2级回退：店铺品类通用表（shop_id + category + gender）
        if (shopId != null && shopId > 0 && category != null && !category.isEmpty()) {
            List<SizeChartReference> shopChart = queryByShopAndCategory(shopId, category, gender);
            if (!shopChart.isEmpty()) {
                return shopChart;
            }
        }

        // 第3级回退：系统模板（shop_id=0 + category + gender）
        List<SizeChartReference> template = queryByShopAndCategory(SYSTEM_TEMPLATE_SHOP_ID, category, gender);
        if (template.isEmpty()) {
            log.info("[尺码表查询] 商品 itemId={} 品类={} 系统模板也为空，返回空列表", itemId, category);
        }
        return template;
    }

    /**
     * 按 shopId + category + gender 查询尺码表（内部统一查询方法）
     * <p>- category 为空：查该 shopId 下所有品类（按 category, sort_order 升序）
     * <p>- gender 为空：查该品类下所有性别
     * <p>- gender 非空：查对应性别 + unisex（unisex 男女通用）
     */
    private List<SizeChartReference> queryByShopAndCategory(Long shopId, String category, String gender) {
        if (shopId == null) {
            return CollUtils.emptyList();
        }
        if (category == null || category.isEmpty()) {
            return lambdaQuery()
                    .eq(SizeChartReference::getShopId, shopId)
                    .orderByAsc(SizeChartReference::getCategory)
                    .orderByAsc(SizeChartReference::getSortOrder)
                    .list();
        }
        if (gender == null || gender.isEmpty()) {
            return lambdaQuery()
                    .eq(SizeChartReference::getShopId, shopId)
                    .eq(SizeChartReference::getCategory, category)
                    .orderByAsc(SizeChartReference::getSortOrder)
                    .list();
        }
        return lambdaQuery()
                .eq(SizeChartReference::getShopId, shopId)
                .eq(SizeChartReference::getCategory, category)
                .in(SizeChartReference::getGender, gender, "unisex")
                .orderByAsc(SizeChartReference::getSortOrder)
                .list();
    }

    @Override
    public SizeRecommendResult recommendSize(BodyProfileDTO bodyProfile, String category) {
        SizeRecommendResult result = new SizeRecommendResult();

        if (bodyProfile == null || category == null) {
            result.setRecommendedSize("未知");
            result.setConfidence(0.0);
            result.setReason("身体信息或品类为空，无法推荐尺码");
            result.setAlternatives(new ArrayList<>());
            return result;
        }

        // 配饰/其他：均码
        if (!CATEGORY_WEIGHTS.containsKey(category)) {
            result.setRecommendedSize("均码");
            result.setConfidence(1.0);
            result.setReason("该品类为均码，无需尺码推荐");
            result.setAlternatives(new ArrayList<>());
            return result;
        }

        // 查询该品类的尺码对照表（系统模板，shop_id=0）
        List<SizeChartReference> sizeChart = querySizeChart(category, bodyProfile.getGender());
        if (CollUtils.isEmpty(sizeChart)) {
            result.setRecommendedSize("未知");
            result.setConfidence(0.0);
            result.setReason("未找到" + category + "的尺码对照表");
            result.setAlternatives(new ArrayList<>());
            return result;
        }

        return doRecommend(bodyProfile, category, sizeChart);
    }

    @Override
    public SizeRecommendResult recommendSizeByItem(BodyProfileDTO bodyProfile, Long itemId) {
        SizeRecommendResult result = new SizeRecommendResult();

        if (bodyProfile == null || itemId == null) {
            result.setRecommendedSize("未知");
            result.setConfidence(0.0);
            result.setReason("身体信息或商品ID为空，无法推荐尺码");
            result.setAlternatives(new ArrayList<>());
            return result;
        }

        // 查询商品对应的尺码表（三级回退：商品专用 > 店铺通用 > 系统模板）
        List<SizeChartReference> sizeChart = getItemSizeChart(itemId);
        if (CollUtils.isEmpty(sizeChart)) {
            result.setRecommendedSize("未知");
            result.setConfidence(0.0);
            result.setReason("商品 itemId=" + itemId + " 未找到对应尺码对照表");
            result.setAlternatives(new ArrayList<>());
            return result;
        }

        // 用尺码表中的品类做均码判断（同一条尺码表的 category 一致）
        String category = sizeChart.get(0).getCategory();
        if (!CATEGORY_WEIGHTS.containsKey(category)) {
            result.setRecommendedSize("均码");
            result.setConfidence(1.0);
            result.setReason("该品类为均码，无需尺码推荐");
            result.setAlternatives(new ArrayList<>());
            return result;
        }

        return doRecommend(bodyProfile, category, sizeChart);
    }

    /**
     * 算法核心：基于已查询到的尺码表 + 用户身体信息计算匹配度，返回推荐结果
     * <p>被 {@link #recommendSize} 和 {@link #recommendSizeByItem} 复用
     */
    private SizeRecommendResult doRecommend(BodyProfileDTO bodyProfile, String category,
                                            List<SizeChartReference> sizeChart) {
        SizeRecommendResult result = new SizeRecommendResult();

        // 计算每个尺码的匹配度
        Map<String, Double> weights = CATEGORY_WEIGHTS.get(category);
        List<SizeMatch> matches = new ArrayList<>();

        for (SizeChartReference sizeRef : sizeChart) {
            double totalScore = 0.0;
            double totalWeight = 0.0;
            List<String> matchDetails = new ArrayList<>();

            for (Map.Entry<String, Double> entry : weights.entrySet()) {
                String field = entry.getKey();
                double weight = entry.getValue();
                Double fieldScore = calculateFieldScore(bodyProfile, sizeRef, field);
                if (fieldScore != null) {
                    totalScore += fieldScore * weight;
                    totalWeight += weight;
                    if (fieldScore < 0.5) {
                        matchDetails.add(field + "偏离区间");
                    }
                }
            }

            // 归一化（用户未填的字段不计入总分）
            double finalScore = totalWeight > 0 ? totalScore / totalWeight : 0.0;
            matches.add(new SizeMatch(sizeRef.getSizeLabel(), finalScore, matchDetails));
        }

        // 按匹配度降序排序
        matches.sort(Comparator.comparingDouble(SizeMatch::getScore).reversed());

        // 取最高匹配度作为推荐
        SizeMatch best = matches.get(0);
        result.setRecommendedSize(best.sizeLabel);
        result.setConfidence(best.score);
        result.setReason(buildReason(bodyProfile, category, best));

        // 备选尺码（置信度 > 0.3 且非推荐尺码）
        List<SizeRecommendResult.AlternativeSize> alternatives = matches.stream()
                .skip(1)
                .filter(m -> m.score > 0.3)
                .map(m -> new SizeRecommendResult.AlternativeSize(m.sizeLabel, m.score))
                .collect(Collectors.toList());
        result.setAlternatives(alternatives);

        log.info("[尺码推荐] category={}, gender={}, height={}, bust={} → 推荐{}码, 置信度={}",
                category, bodyProfile.getGender(), bodyProfile.getHeight(),
                bodyProfile.getBust(), best.sizeLabel, String.format("%.2f", best.score));

        return result;
    }

    /**
     * 计算单个字段的匹配分（0-1）
     * 在区间内=1.0，区间外按距离衰减
     */
    private Double calculateFieldScore(BodyProfileDTO profile, SizeChartReference sizeRef, String field) {
        switch (field) {
            case "height":
                return calcRangeScore(profile.getHeight() != null ? profile.getHeight().doubleValue() : null,
                        sizeRef.getHeightMin() != null ? sizeRef.getHeightMin().doubleValue() : null,
                        sizeRef.getHeightMax() != null ? sizeRef.getHeightMax().doubleValue() : null);
            case "weight":
                return calcRangeScore(profile.getWeight() != null ? profile.getWeight().doubleValue() : null,
                        sizeRef.getWeightMin() != null ? sizeRef.getWeightMin().doubleValue() : null,
                        sizeRef.getWeightMax() != null ? sizeRef.getWeightMax().doubleValue() : null);
            case "bust":
                return calcRangeScore(profile.getBust() != null ? profile.getBust().doubleValue() : null,
                        sizeRef.getBustMin() != null ? sizeRef.getBustMin().doubleValue() : null,
                        sizeRef.getBustMax() != null ? sizeRef.getBustMax().doubleValue() : null);
            case "shoulder_width":
                return calcRangeScore(profile.getShoulderWidth() != null ? profile.getShoulderWidth().doubleValue() : null,
                        sizeRef.getShoulderWidthMin() != null ? sizeRef.getShoulderWidthMin().doubleValue() : null,
                        sizeRef.getShoulderWidthMax() != null ? sizeRef.getShoulderWidthMax().doubleValue() : null);
            case "waist":
                return calcRangeScore(profile.getWaist() != null ? profile.getWaist().doubleValue() : null,
                        sizeRef.getWaistMin() != null ? sizeRef.getWaistMin().doubleValue() : null,
                        sizeRef.getWaistMax() != null ? sizeRef.getWaistMax().doubleValue() : null);
            case "hip":
                return calcRangeScore(profile.getHip() != null ? profile.getHip().doubleValue() : null,
                        sizeRef.getHipMin() != null ? sizeRef.getHipMin().doubleValue() : null,
                        sizeRef.getHipMax() != null ? sizeRef.getHipMax().doubleValue() : null);
            case "foot_length":
                return calcRangeScore(profile.getFootLength() != null ? profile.getFootLength().doubleValue() : null,
                        sizeRef.getFootLengthMin() != null ? sizeRef.getFootLengthMin().doubleValue() : null,
                        sizeRef.getFootLengthMax() != null ? sizeRef.getFootLengthMax().doubleValue() : null);
            case "foot_width":
                return calcRangeScore(profile.getFootWidth() != null ? profile.getFootWidth().doubleValue() : null,
                        null, null); // 脚宽暂无区间，返回 null
            case "head_circumference":
                return calcRangeScore(profile.getHeadCircumference() != null ? profile.getHeadCircumference().doubleValue() : null,
                        sizeRef.getHeadCircumferenceMin() != null ? sizeRef.getHeadCircumferenceMin().doubleValue() : null,
                        sizeRef.getHeadCircumferenceMax() != null ? sizeRef.getHeadCircumferenceMax().doubleValue() : null);
            default:
                return null;
        }
    }

    /**
     * 计算数值在区间内的匹配分
     * - 在区间内：1.0
     * - 区间外：按距离衰减，距离越远分越低（最低 0）
     * - null（用户未填或区间未定义）：返回 null（不计入总分）
     */
    private Double calcRangeScore(Double value, Double min, Double max) {
        if (value == null || min == null || max == null) {
            return null;
        }
        if (value >= min && value <= max) {
            return 1.0;
        }
        // 区间外按距离衰减
        double range = max - min;
        if (range <= 0) {
            return 0.0;
        }
        double distance = value < min ? (min - value) : (value - max);
        // 距离每增加 1 个区间长度，分数降 0.5
        double score = 1.0 - 0.5 * (distance / range);
        return Math.max(0.0, score);
    }

    private String buildReason(BodyProfileDTO profile, String category, SizeMatch best) {
        StringBuilder sb = new StringBuilder();
        if (profile.getHeight() != null) {
            sb.append("身高").append(profile.getHeight()).append("cm ");
        }
        if ("上衣".equals(category) || "外套".equals(category)) {
            if (profile.getBust() != null) {
                sb.append("胸围").append(profile.getBust()).append("cm ");
            }
            if (profile.getShoulderWidth() != null) {
                sb.append("肩宽").append(profile.getShoulderWidth()).append("cm ");
            }
        } else if ("下装".equals(category) || "裤子".equals(category)) {
            if (profile.getWaist() != null) {
                sb.append("腰围").append(profile.getWaist()).append("cm ");
            }
            if (profile.getHip() != null) {
                sb.append("臀围").append(profile.getHip()).append("cm ");
            }
        } else if ("鞋".equals(category)) {
            if (profile.getFootLength() != null) {
                sb.append("脚长").append(profile.getFootLength()).append("cm ");
            }
        } else if ("帽子".equals(category)) {
            if (profile.getHeadCircumference() != null) {
                sb.append("头围").append(profile.getHeadCircumference()).append("cm ");
            }
        }
        sb.append("匹配 ").append(best.sizeLabel).append(" 码区间");
        if (!best.details.isEmpty()) {
            sb.append("（部分字段偏离：").append(String.join("、", best.details)).append("）");
        }
        return sb.toString();
    }

    // ============================================================
    // 商家后台 CRUD（带店铺所有权校验）
    // ============================================================

    @Override
    public boolean addShopSizeChart(Long shopId, SizeChartReference sizeChart) {
        if (shopId == null || shopId <= 0) {
            throw new IllegalArgumentException("店铺ID无效");
        }
        if (sizeChart == null) {
            throw new IllegalArgumentException("尺码记录不能为空");
        }
        // 强制覆盖 shopId，防止前端伪造越权
        sizeChart.setShopId(shopId);
        sizeChart.setId(null); // 新增时清空 id，防止误更新已有记录
        boolean ok = save(sizeChart);
        log.info("[尺码表新增] shopId={}, category={}, sizeLabel={}, ok={}",
                shopId, sizeChart.getCategory(), sizeChart.getSizeLabel(), ok);
        return ok;
    }

    @Override
    public boolean updateShopSizeChart(Long shopId, SizeChartReference sizeChart) {
        if (shopId == null || shopId <= 0) {
            throw new IllegalArgumentException("店铺ID无效");
        }
        if (sizeChart == null || sizeChart.getId() == null) {
            throw new IllegalArgumentException("尺码记录或ID不能为空");
        }
        // 所有权校验：仅允许修改自己店铺的记录
        SizeChartReference existing = getById(sizeChart.getId());
        if (existing == null) {
            throw new IllegalArgumentException("尺码记录不存在 id=" + sizeChart.getId());
        }
        if (!shopId.equals(existing.getShopId())) {
            throw new com.hmall.common.exception.BizIllegalException("无权修改他人店铺的尺码表");
        }
        // 强制覆盖 shopId，防止越权修改
        sizeChart.setShopId(shopId);
        boolean ok = updateById(sizeChart);
        log.info("[尺码表修改] shopId={}, id={}, category={}, sizeLabel={}, ok={}",
                shopId, sizeChart.getId(), sizeChart.getCategory(), sizeChart.getSizeLabel(), ok);
        return ok;
    }

    @Override
    public boolean deleteShopSizeChart(Long shopId, Long id) {
        if (shopId == null || shopId <= 0) {
            throw new IllegalArgumentException("店铺ID无效");
        }
        if (id == null) {
            throw new IllegalArgumentException("尺码记录ID不能为空");
        }
        // 所有权校验：仅允许删除自己店铺的记录
        SizeChartReference existing = getById(id);
        if (existing == null) {
            log.warn("[尺码表删除] 记录不存在 id={}, shopId={}, 视为已删除", id, shopId);
            return false;
        }
        if (!shopId.equals(existing.getShopId())) {
            throw new com.hmall.common.exception.BizIllegalException("无权删除他人店铺的尺码表");
        }
        boolean ok = removeById(id);
        log.info("[尺码表删除] shopId={}, id={}, ok={}", shopId, id, ok);
        return ok;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public int copyTemplateToShop(Long shopId, String category, String gender) {
        if (shopId == null || shopId <= 0) {
            throw new IllegalArgumentException("店铺ID无效");
        }
        // 查询系统模板（shop_id=0）
        List<SizeChartReference> templates = queryByShopAndCategory(SYSTEM_TEMPLATE_SHOP_ID, category, gender);
        if (templates.isEmpty()) {
            log.info("[模板复制] 无可复制的模板 shopId={}, category={}, gender={}", shopId, category, gender);
            return 0;
        }
        // 查询该店铺已有的尺码记录，构建去重 key：(category, gender, sizeLabel)
        List<SizeChartReference> existing = queryByShopAndCategory(shopId, category, null);
        java.util.Set<String> existingKeys = existing.stream()
                .map(r -> r.getCategory() + "|" + r.getGender() + "|" + r.getSizeLabel())
                .collect(Collectors.toSet());

        int copied = 0;
        for (SizeChartReference tpl : templates) {
            String key = tpl.getCategory() + "|" + tpl.getGender() + "|" + tpl.getSizeLabel();
            if (existingKeys.contains(key)) {
                continue; // 已存在，跳过
            }
            // 复制模板，重置 id 和 shopId
            tpl.setId(null);
            tpl.setShopId(shopId);
            save(tpl);
            copied++;
        }
        log.info("[模板复制] shopId={}, category={}, gender={}, 模板数={}, 实际复制={}",
                shopId, category, gender, templates.size(), copied);
        return copied;
    }

    /**
     * 尺码匹配内部类
     */
    private static class SizeMatch {
        String sizeLabel;
        double score;
        List<String> details;

        SizeMatch(String sizeLabel, double score, List<String> details) {
            this.sizeLabel = sizeLabel;
            this.score = score;
            this.details = details;
        }

        double getScore() {
            return score;
        }
    }
}
