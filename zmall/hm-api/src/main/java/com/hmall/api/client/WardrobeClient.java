package com.hmall.api.client;

import com.hmall.api.client.fallback.WardrobeClientFallbackFactory;
import com.hmall.api.dto.WardrobeDTO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.Collection;
import java.util.List;

@FeignClient(contextId = "wardrobeClient", value = "user-service", fallbackFactory = WardrobeClientFallbackFactory.class)
public interface WardrobeClient {

    /**
     * 服务间调用：查询指定用户的衣橱列表
     */
    @GetMapping("/wardrobe/list")
    List<WardrobeDTO> queryUserWardrobe(@RequestParam("userId") Long userId);

    /**
     * 服务间调用：批量查询衣橱条目
     */
    @GetMapping("/wardrobe/items")
    List<WardrobeDTO> queryWardrobeByIds(@RequestParam("ids") Collection<Long> ids);

    /**
     * 服务间调用：查询指定用户衣橱中所有 item_id 列表（用于排除已加衣橱的商品）
     * P1-9 修复：补全与 WardrobeController#queryMyWardrobeItemIds 对应的 Feign 方法
     */
    @GetMapping("/wardrobe/my-item-ids")
    List<Long> queryMyWardrobeItemIds(@RequestParam("userId") Long userId);

    /**
     * 服务间调用：AI 满意搭配效果图自动写入衣橱（item_type=4，v3.1 新增）
     *
     * <p>由 Python ai-outfit accept 流程在 create_outfit_record 成功后调用，
     * 把 AI 搭配效果图（含原自拍照 + 效果图 + 单品信息）写入 user_wardrobe。
     * 用户在"我的衣橱"页面可回看：用户原自拍照 + AI 穿搭效果图 + 对应单品信息。
     *
     * <p>失败容忍：调用失败走 FallbackFactory 返回 null，不影响 accept 主流程。
     */
    @PostMapping("/wardrobe/internal")
    WardrobeDTO addWardrobeOutfit(@RequestBody WardrobeDTO dto);

    /**
     * 服务间调用：按搭配记录删除衣橱条目（用户取消满意/改不满意时联动删除，软删除）
     *
     * <p>item-service 在 upsert 搭配记录时检测到 accepted 从 1 → 非 1（满意变为取消满意/不满意），
     * 调用本方法删除 user_wardrobe 中 record_id 对应的条目（item_type=4）。
     *
     * <p>失败容忍：调用失败走 FallbackFactory，不影响记录状态更新主流程。
     */
    @DeleteMapping("/wardrobe/by-record/{recordId}")
    void removeByRecord(@PathVariable("recordId") Long recordId);
}
