package com.hmall.item.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmall.api.dto.BodyProfileDTO;
import com.hmall.item.domain.po.SizeChartReference;
import com.hmall.item.domain.vo.SizeRecommendResult;

import java.util.List;

/**
 * <p>
 * 尺码对照参考表 服务类
 * </p>
 *
 * <p>2026-07-27 改造为店铺维度：
 * <ul>
 *   <li>shop_id = 0  → 系统预置模板（只读，商家可一键复制到自己店铺）</li>
 *   <li>shop_id > 0  → 商家自己维护的尺码表（商家后台 CRUD 管理）</li>
 * </ul>
 *
 * @author hmall
 * @since 2026-07-27
 */
public interface ISizeChartReferenceService extends IService<SizeChartReference> {

    /**
     * 查询尺码对照表（按品类+性别）—— 系统模板（向后兼容）
     * <p>语义等价于 {@link #queryTemplates}，查 shop_id=0 的系统预置数据。
     *
     * @param category 品类
     * @param gender   性别（male/female/unisex，null 或空时不过滤）
     */
    List<SizeChartReference> querySizeChart(String category, String gender);

    /**
     * 查询系统模板（只读，商家可参考或一键复制）
     */
    List<SizeChartReference> queryTemplates(String category, String gender);

    /**
     * 商家查询自己店铺的尺码表
     *
     * @param shopId   店铺ID（即商家用户ID）
     * @param category 品类（可选，null 时查全店铺所有品类）
     * @param gender   性别（可选）
     */
    List<SizeChartReference> queryShopSizeChart(Long shopId, String category, String gender);

    /**
     * 商品详情页：查询商品对应的尺码表（含三级回退）
     * <p>查询优先级：
     * <ol>
     *   <li>商品专用绑定（item.size_chart_id 非空时）</li>
     *   <li>店铺品类通用表（shop_id + category + gender）</li>
     *   <li>系统模板（shop_id = 0 + category + gender）</li>
     * </ol>
     *
     * @param itemId 商品ID
     * @return 尺码对照表（按 sort_order 升序）；若商品不存在或品类为空返回空列表
     */
    List<SizeChartReference> getItemSizeChart(Long itemId);

    /**
     * 推荐尺码（单件商品）—— 基于系统模板（向后兼容）
     * <p>AI 随心搭场景推荐使用 {@link #recommendSizeByItem}，会按商品所属店铺查询尺码表。
     */
    SizeRecommendResult recommendSize(BodyProfileDTO bodyProfile, String category);

    /**
     * 按商品推荐尺码（含三级回退查询 + 算法匹配）
     * <p>自动按商品 itemId 查询对应的尺码表（商品专用 > 店铺通用 > 系统模板），
     * 再基于用户身体信息计算匹配度。
     *
     * @param bodyProfile 用户身体信息
     * @param itemId      商品ID
     */
    SizeRecommendResult recommendSizeByItem(BodyProfileDTO bodyProfile, Long itemId);

    /**
     * 商家新增尺码记录（自动注入 shopId，忽略前端传入的 shopId）
     *
     * @param shopId    店铺ID
     * @param sizeChart 尺码记录（shopId 字段会被覆盖为传入的 shopId）
     */
    boolean addShopSizeChart(Long shopId, SizeChartReference sizeChart);

    /**
     * 商家修改尺码记录（带所有权校验）
     * <p>仅允许修改自己店铺（shop_id=shopId）的记录，禁止修改系统模板（shop_id=0）。
     *
     * @param shopId    店铺ID
     * @param sizeChart 尺码记录（id 必填，shopId 字段会被覆盖为传入的 shopId 防止越权）
     */
    boolean updateShopSizeChart(Long shopId, SizeChartReference sizeChart);

    /**
     * 商家删除尺码记录（带所有权校验）
     * <p>仅允许删除自己店铺（shop_id=shopId）的记录，禁止删除系统模板（shop_id=0）。
     *
     * @param shopId 店铺ID
     * @param id     尺码记录ID
     */
    boolean deleteShopSizeChart(Long shopId, Long id);

    /**
     * 商家一键复制系统模板到自己店铺
     * <p>将 shop_id=0 的系统模板按 (category, gender) 过滤后复制到指定店铺。
     * 已存在的同 (shopId, category, gender, sizeLabel) 记录会跳过，避免重复。
     *
     * @param shopId   目标店铺ID
     * @param category 品类（null=复制全部品类）
     * @param gender   性别（null=复制全部性别）
     * @return 实际复制条数
     */
    int copyTemplateToShop(Long shopId, String category, String gender);
}
