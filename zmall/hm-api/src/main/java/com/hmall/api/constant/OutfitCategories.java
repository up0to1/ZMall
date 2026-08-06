package com.hmall.api.constant;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * AI 随心搭·穿搭类目清单（单一真相源）
 *
 * <p>平台商品类目众多（手机/拉拉裤/拉杆箱等），但 AI 随心搭仅服务穿搭相关类目。
 * 本类定义"哪些类目需要同步到 Qdrant 向量库"以及"默认搭配组合"。
 *
 * <p>Java 侧（ItemServiceImpl 发 MQ 前）/ Python 侧（item_sync_consumer 消费前）
 * 都引用此清单做过滤，避免非穿搭商品污染 Qdrant。
 *
 * <p>与 Python 侧 shared/qdrant_client/category_mapping.py 的 CN_TO_EN 保持一致。
 *
 * <p>变更本清单时需同步修改 Python 侧映射表。
 *
 * <p>全身套装说明：成套衣服/连衣裙/连体衣/旗袍等"一件即覆盖全身"的成套衣物归为"全身套装"
 * （一次 VTON 即完成全身换装，等价于[上衣+下装]）；半身裙归为"下装"。
 * 商品上架时需正确填写 category 字段。
 */
public final class OutfitCategories {

    private OutfitCategories() {}

    /** 穿搭类目中文清单（与 MySQL item.category 字符串匹配） */
    public static final List<String> OUTFIT_CATEGORIES_CN =
            Collections.unmodifiableList(Arrays.asList(
                    "上衣",
                    "下装",
                    "全身套装",
                    "鞋",
                    "帽子",
                    "包",
                    "配饰"
            ));

    /**
     * AI 模特（商家端）支持的品类子清单
     *
     * <p>设计文档 §1.0：AI 模特只做服装主体（上衣/下装/全身套装/帽子 4 类），
     * 不支持鞋/包/配饰（与随心搭 7 类清单不同）。
     *
     * <p>品类冲突规则（设计文档 §1.0）：
     * <ul>
     *   <li>同品类最多 1 件（Kolors VTON 单次只能穿 1 件同类商品）</li>
     *   <li>全身套装与上衣/下装互斥（全身套装已覆盖上下身，逻辑矛盾）</li>
     *   <li>全身套装与帽子可共存（套装→帽子 2 次生成）</li>
     * </ul>
     *
     * <p>允许的 9 种合法组合：
     * [上衣]、[下装]、[全身套装]、[帽子]、[上衣+下装]、[上衣+帽子]、[下装+帽子]、
     * [上衣+下装+帽子]、[全身套装+帽子]
     */
    public static final List<String> AI_MODEL_SUPPORT_CATEGORIES =
            Collections.unmodifiableList(Arrays.asList(
                    "上衣",
                    "下装",
                    "全身套装",
                    "帽子"
            ));

    /** AI 模特支持品类快速判断集合 */
    public static final Set<String> AI_MODEL_SUPPORT_CATEGORIES_SET =
            new HashSet<>(AI_MODEL_SUPPORT_CATEGORIES);

    /** 默认搭配三件套（上衣 + 下装 + 鞋） */
    public static final List<String> DEFAULT_OUTFIT_COMBO_CN =
            Collections.unmodifiableList(Arrays.asList(
                    "上衣",
                    "下装",
                    "鞋"
            ));

    /** 快速判断集合（O(1) 查询） */
    public static final Set<String> OUTFIT_CATEGORIES_CN_SET =
            new HashSet<>(OUTFIT_CATEGORIES_CN);

    /**
     * 判断类目是否为穿搭类目（仅穿搭类目才会同步到 Qdrant）
     * @param category MySQL item.category 字段（中文）
     * @return true=穿搭类目需同步，false=非穿搭类目跳过
     */
    public static boolean isOutfitCategory(String category) {
        return category != null && OUTFIT_CATEGORIES_CN_SET.contains(category);
    }

    /**
     * 判断类目是否为 AI 模特支持品类
     * @param category MySQL item.category 字段（中文）
     * @return true=AI 模特支持，false=不支持
     */
    public static boolean isAiModelSupportCategory(String category) {
        return category != null && AI_MODEL_SUPPORT_CATEGORIES_SET.contains(category);
    }

    /**
     * 校验 AI 模特商品组合是否满足品类冲突规则（single 模式）
     *
     * <p>校验规则：
     * <ul>
     *   <li>同品类最多 1 件</li>
     *   <li>全身套装与上衣/下装互斥</li>
     * </ul>
     *
     * @param categories 商品品类列表（中文）
     * @return null=校验通过；非空=校验失败的错误信息
     */
    public static String validateAiModelCategoryCombo(List<String> categories) {
        return validateAiModelCategoryCombo(categories, "single");
    }

    /**
     * 校验 AI 模特商品组合是否满足品类冲突规则（按生成模式）
     *
     * <p>v5 新增（2026-07-26）：多图模式校验规则
     * <ul>
     *   <li>single / multi_pose 模式：同品类最多 1 件 + 全身套装与上衣/下装互斥（保持 v2 规则）</li>
     *   <li>multi_outfit 模式：放宽同品类限制，允许 2 件下装 + 1 件上装（多套搭配）
     *       <p>规则：上衣最多 2 件，下装最多 2 件，全身套装最多 1 件，帽子最多 1 件；
     *       全身套装与上衣/下装互斥保持不变（每套组合内仍走 single 校验）</li>
     * </ul>
     *
     * @param categories 商品品类列表（中文）
     * @param generationMode 生成模式："single" / "multi_outfit" / "multi_pose"
     * @return null=校验通过；非空=校验失败的错误信息
     */
    public static String validateAiModelCategoryCombo(List<String> categories, String generationMode) {
        if (categories == null || categories.isEmpty()) {
            return "商品品类列表不能为空";
        }

        // 1. 校验是否都是 AI 模特支持品类
        for (String cat : categories) {
            if (!isAiModelSupportCategory(cat)) {
                return "非支持品类：" + cat + "，AI 模特仅支持上衣/下装/全身套装/帽子";
            }
        }

        // 2. 多换装模式放宽同品类限制：允许 2 件下装 + 1 件上装
        if ("multi_outfit".equals(generationMode)) {
            // 统计各品类数量
            int topCount = 0, bottomCount = 0, dressCount = 0, hatCount = 0;
            for (String cat : categories) {
                switch (cat) {
                    case "上衣": topCount++; break;
                    case "下装": bottomCount++; break;
                    case "全身套装": dressCount++; break;
                    case "帽子": hatCount++; break;
                }
            }
            if (topCount > 2) {
                return "多换装模式：上衣最多 2 件，当前 " + topCount + " 件";
            }
            if (bottomCount > 2) {
                return "多换装模式：下装最多 2 件，当前 " + bottomCount + " 件";
            }
            if (dressCount > 1) {
                return "多换装模式：全身套装最多 1 件，当前 " + dressCount + " 件";
            }
            if (hatCount > 1) {
                return "多换装模式：帽子最多 1 件，当前 " + hatCount + " 件";
            }
            // 互斥规则保持：全身套装与上衣/下装不可同时存在
            if (dressCount > 0 && (topCount > 0 || bottomCount > 0)) {
                return "全身套装已覆盖上下身，不可与上衣/下装同时选择";
            }
            // 多换装至少需要 2 件商品才能组合（1 件无搭配意义）
            if (categories.size() < 2) {
                return "多换装模式至少需要 2 件商品才能组合搭配";
            }
            return null;
        }

        // 3. single / multi_pose 模式：保持原 v2 规则
        // 同品类最多 1 件
        Set<String> seen = new HashSet<>();
        for (String cat : categories) {
            if (!seen.add(cat)) {
                return "同品类商品只能选 1 件，请重新选择（重复品类：" + cat + "）";
            }
        }

        // 全身套装与上衣/下装互斥
        if (seen.contains("全身套装") && (seen.contains("上衣") || seen.contains("下装"))) {
            return "全身套装已覆盖上下身，不可与上衣/下装同时选择";
        }

        return null;
    }

    /**
     * 按 VTON 链式顺序排好品类（全身套装→上衣→下装→帽子）
     *
     * <p>设计文档 §1.0：全身套装优先，避免被上衣/下装覆盖。
     *
     * @param categories 商品品类列表（中文，已通过 validateAiModelCategoryCombo 校验）
     * @return 按链式顺序排好的品类列表
     */
    public static List<String> sortByVtonChainOrder(List<String> categories) {
        if (categories == null || categories.isEmpty()) {
            return java.util.Collections.emptyList();
        }
        List<String> ordered = new java.util.ArrayList<>();
        for (String cat : AI_MODEL_SUPPORT_CATEGORIES) {
            if (categories.contains(cat)) {
                ordered.add(cat);
            }
        }
        return ordered;
    }
}
