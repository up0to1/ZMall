package com.hmall.item.controller;

import com.hmall.api.dto.BodyProfileDTO;
import com.hmall.common.utils.UserContext;
import com.hmall.item.domain.dto.BodyProfileSimpleDTO;
import com.hmall.item.domain.dto.SizeRecommendBatchRequest;
import com.hmall.item.domain.dto.SizeRecommendRequest;
import com.hmall.item.domain.po.SizeChartReference;
import com.hmall.item.domain.vo.SizeRecommendResult;
import com.hmall.item.service.ISizeChartReferenceService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 尺码对照与推荐接口
 *
 * <p>2026-07-27 新增：系统维护统一尺码对照参考表，按品类+性别组织，
 * 根据用户身体信息推荐合适尺码。
 *
 * <p>2026-07-27 改造为店铺维度：
 * <ul>
 *   <li>系统模板（shop_id=0）只读，商家可参考或一键复制到自己店铺</li>
 *   <li>商家后台 CRUD 自己店铺的尺码表（shop_id=商家用户ID）</li>
 *   <li>商品详情页通过三级回退查询对应尺码表（商品专用 > 店铺通用 > 系统模板）</li>
 * </ul>
 *
 * <p>接口分组：
 * <ul>
 *   <li>通用接口（reference / templates / item / recommend / recommend-by-item）：C端 + AI</li>
 *   <li>商家后台接口（/shop/**）：商家管理自己店铺的尺码表</li>
 * </ul>
 *
 * @author hmall
 * @since 2026-07-27
 */
@Api(tags = "尺码对照与推荐接口")
@RestController
@RequestMapping("/items/size-chart")
@RequiredArgsConstructor
public class SizeChartController {

    private final ISizeChartReferenceService sizeChartService;

    // ============================================================
    // 通用接口：系统模板查询 + 商品详情页 + 尺码推荐
    // ============================================================

    @ApiOperation("查询尺码对照表（按品类+性别，向后兼容接口，查系统模板）")
    @GetMapping("/reference")
    public List<SizeChartReference> querySizeChart(
            @RequestParam("category") String category,
            @RequestParam(value = "gender", required = false) String gender) {
        return sizeChartService.querySizeChart(category, gender);
    }

    @ApiOperation("查询系统模板（只读，商家参考用）")
    @GetMapping("/templates")
    public List<SizeChartReference> queryTemplates(
            @RequestParam(value = "category", required = false) String category,
            @RequestParam(value = "gender", required = false) String gender) {
        return sizeChartService.queryTemplates(category, gender);
    }

    @ApiOperation("商品详情页：查询商品对应的尺码表（三级回退）")
    @GetMapping("/item/{itemId}")
    public List<SizeChartReference> getItemSizeChart(@PathVariable("itemId") Long itemId) {
        return sizeChartService.getItemSizeChart(itemId);
    }

    @ApiOperation("推荐尺码（基于系统模板，向后兼容）")
    @PostMapping("/recommend")
    public SizeRecommendResult recommendSize(@RequestBody @Validated SizeRecommendRequest request) {
        BodyProfileDTO bodyProfile = convertToDTO(request.getBodyProfile());
        return sizeChartService.recommendSize(bodyProfile, request.getCategory());
    }

    @ApiOperation("按商品推荐尺码（含三级回退查询，AI 随心搭场景）")
    @PostMapping("/recommend-by-item")
    public SizeRecommendResult recommendSizeByItem(
            @RequestParam("itemId") Long itemId,
            @RequestBody @Validated BodyProfileSimpleDTO bodyProfileSimple) {
        BodyProfileDTO bodyProfile = convertToDTO(bodyProfileSimple);
        return sizeChartService.recommendSizeByItem(bodyProfile, itemId);
    }

    @ApiOperation("批量推荐尺码（搭配选购场景，按商品三级回退查询）")
    @PostMapping("/recommend-batch")
    public Map<Long, SizeRecommendResult> recommendSizeBatch(
            @RequestBody @Validated SizeRecommendBatchRequest request) {
        BodyProfileDTO bodyProfile = convertToDTO(request.getBodyProfile());
        Map<Long, SizeRecommendResult> results = new HashMap<>();
        for (Long itemId : request.getItemIds()) {
            // 2026-07-27 改造：批量场景也走 recommendSizeByItem 三级回退查询，
            // 让 AI 随心搭搭配的每件单品都能匹配到对应店铺的尺码表
            SizeRecommendResult result = sizeChartService.recommendSizeByItem(bodyProfile, itemId);
            results.put(itemId, result);
        }
        return results;
    }

    // ============================================================
    // 商家后台接口：店铺尺码表 CRUD + 一键复制系统模板
    // ============================================================

    @ApiOperation("商家查询自己店铺的尺码表")
    @GetMapping("/shop/list")
    public List<SizeChartReference> queryShopSizeChart(
            @RequestParam(value = "category", required = false) String category,
            @RequestParam(value = "gender", required = false) String gender) {
        Long shopId = UserContext.getUser();
        return sizeChartService.queryShopSizeChart(shopId, category, gender);
    }

    @ApiOperation("商家新增尺码记录")
    @PostMapping("/shop")
    public boolean addShopSizeChart(@RequestBody SizeChartReference sizeChart) {
        Long shopId = UserContext.getUser();
        return sizeChartService.addShopSizeChart(shopId, sizeChart);
    }

    @ApiOperation("商家修改尺码记录（带所有权校验）")
    @PutMapping("/shop/{id}")
    public boolean updateShopSizeChart(@PathVariable("id") Long id,
                                       @RequestBody SizeChartReference sizeChart) {
        Long shopId = UserContext.getUser();
        sizeChart.setId(id);
        return sizeChartService.updateShopSizeChart(shopId, sizeChart);
    }

    @ApiOperation("商家删除尺码记录（带所有权校验）")
    @DeleteMapping("/shop/{id}")
    public boolean deleteShopSizeChart(@PathVariable("id") Long id) {
        Long shopId = UserContext.getUser();
        return sizeChartService.deleteShopSizeChart(shopId, id);
    }

    @ApiOperation("商家一键复制系统模板到自己店铺（去重）")
    @PostMapping("/shop/copy-template")
    public int copyTemplateToShop(
            @RequestParam(value = "category", required = false) String category,
            @RequestParam(value = "gender", required = false) String gender) {
        Long shopId = UserContext.getUser();
        return sizeChartService.copyTemplateToShop(shopId, category, gender);
    }

    // ============================================================
    // 内部工具方法
    // ============================================================

    /**
     * BodyProfileSimpleDTO → BodyProfileDTO（复用 service 层逻辑）
     */
    private BodyProfileDTO convertToDTO(BodyProfileSimpleDTO simple) {
        BodyProfileDTO dto = new BodyProfileDTO();
        dto.setGender(simple.getGender());
        dto.setHeight(simple.getHeight());
        dto.setWeight(simple.getWeight());
        dto.setShoulderWidth(simple.getShoulderWidth());
        dto.setBust(simple.getBust());
        dto.setWaist(simple.getWaist());
        dto.setHip(simple.getHip());
        dto.setFootLength(simple.getFootLength());
        dto.setFootWidth(simple.getFootWidth());
        dto.setHeadCircumference(simple.getHeadCircumference());
        return dto;
    }
}
