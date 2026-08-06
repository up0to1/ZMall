package com.hmall.user.enums;

import com.baomidou.mybatisplus.annotation.EnumValue;
import com.hmall.common.exception.BadRequestException;
import lombok.AllArgsConstructor;
import lombok.Getter;

/**
 * AI 配额类型
 *
 * <p>v3 分类：
 * <ul>
 *   <li>{@link #MODEL} — AI 模特（商家维度 shop_id），v3 credits 积分制（P1-10 修复：从旧版次数制迁移）</li>
 *   <li>{@link #OUTFIT} — AI 随心搭商品驱动模式（用户维度 user_id），保留旧版次数制</li>
 *   <li>{@link #OUTFIT_RECOMMEND} — v3 阶段一候选推荐（用户维度 user_id），credits 积分制</li>
 *   <li>{@link #OUTFIT_VTON} — v3 阶段二 VTON 生成（用户维度 user_id），credits 积分制</li>
 *   <li>{@link #OUTFIT_DIRECT} — v3 一阶段直出（用户维度 user_id），credits 积分制，推荐+VTON 合并扣 17 credits</li>
 * </ul>
 *
 * <p>调用方根据 phase 选择 type：
 * <ul>
 *   <li>商品驱动模式（旧版兼容）→ {@link #OUTFIT}</li>
 *   <li>风格驱动 v3 阶段一 → {@link #OUTFIT_RECOMMEND}</li>
 *   <li>风格驱动 v3 阶段二 → {@link #OUTFIT_VTON}</li>
 *   <li>风格驱动 v3 一阶段直出 → {@link #OUTFIT_DIRECT}（推荐+VTON 合并）</li>
 *   <li>AI 模特 → {@link #MODEL}（v3 credits 制，单次任务扣 5 credits）</li>
 * </ul>
 */
@Getter
@AllArgsConstructor
public enum QuotaType {

    /** AI 模特（商家维度 shop_id） — v3 credits 积分制（P1-10 修复：从旧版次数制迁移，单次任务扣 5 credits） */
    MODEL("MODEL"),
    /** AI 随心搭·商品驱动模式（用户维度 user_id） — 旧版次数制 */
    OUTFIT("OUTFIT"),
    /** AI 随心搭·v3 阶段一候选推荐（用户维度 user_id） — credits 积分制 */
    OUTFIT_RECOMMEND("OUTFIT_RECOMMEND"),
    /** AI 随心搭·v3 阶段二 VTON 生成（用户维度 user_id） — credits 积分制 */
    OUTFIT_VTON("OUTFIT_VTON"),
    /** AI 随心搭·v3 一阶段直出（用户维度 user_id） — credits 积分制，推荐+VTON 合并扣 17 credits */
    OUTFIT_DIRECT("OUTFIT_DIRECT");

    @EnumValue
    private final String value;

    public static QuotaType of(String value) {
        for (QuotaType type : QuotaType.values()) {
            if (type.value.equals(value)) {
                return type;
            }
        }
        throw new BadRequestException("未知的配额类型: " + value);
    }

    /**
     * 是否使用 v3 credits 积分制（true=走 CreditsService，false=走旧版 QuotaService 次数制）
     *
     * <p>P1-10 修复：MODEL（AI 模特）从旧版次数制迁移到 v3 credits 积分制，
     * 统一配额体系。商家获得的评分激励 credits（走 /credits/award）可直接用于 AI 模特生成，
     * 不再出现"奖励 credits 无法用于 AI 模特"的割裂问题。单次任务扣 5 credits（设计文档 §0.2）。
     */
    public boolean isCreditsMode() {
        return this == MODEL || this == OUTFIT_RECOMMEND || this == OUTFIT_VTON || this == OUTFIT_DIRECT;
    }
}
