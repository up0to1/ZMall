package com.hmall.user.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmall.common.domain.PageDTO;
import com.hmall.user.domain.po.UserBrowseHistory;
import com.hmall.user.domain.vo.UserBrowseHistoryVO;

import java.util.List;

/**
 * 用户浏览记录服务接口
 */
public interface IUserBrowseHistoryService extends IService<UserBrowseHistory> {

    /**
     * 分页查询当前用户的浏览记录（按 last_viewed_at 倒序）
     *
     * @param pageNum  页码
     * @param pageSize 每页大小
     * @return 浏览记录分页数据（含商品展示信息）
     */
    PageDTO<UserBrowseHistoryVO> queryMyHistory(Integer pageNum, Integer pageSize);

    /**
     * 记录一次商品浏览
     * <p>同一商品已存在则 view_count+1 并更新 last_viewed_at，不存在则新增。
     * <p>新增时通过 Feign 调 item-service 拉取商品的 shopId 和 category，拉取失败不阻塞记录。
     *
     * @param itemId       商品ID
     * @param viewSource   浏览来源：search/recommend/ai_outfit/shop/direct
     * @param viewDuration 停留时长（秒）
     */
    void recordView(Long itemId, String viewSource, Integer viewDuration);

    /**
     * 删除单条浏览记录（校验所属用户）
     *
     * @param id 浏览记录主键ID
     */
    void deleteById(Long id);

    /**
     * 批量删除浏览记录（校验所属用户）
     *
     * @param ids 浏览记录主键ID列表
     */
    void deleteBatch(List<Long> ids);

    /**
     * 清空当前用户所有浏览记录
     */
    void clearAll();
}
