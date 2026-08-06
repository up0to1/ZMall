package com.hmall.item.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmall.api.dto.AiOutfitRecordCreateDTO;
import com.hmall.api.dto.AiOutfitRecordDTO;
import com.hmall.api.dto.AiOutfitHistoryDTO;
import com.hmall.item.domain.po.AiOutfitRecord;

import java.util.List;

/**
 * AI 随心搭效果图入库服务（v3 新增）
 *
 * <p>职责：
 * <ul>
 *   <li>Python ai-outfit 调用入库（用户满意加购/下单时）</li>
 *   <li>用户查询"我的搭配历史"列表 + 单条详情</li>
 *   <li>用户主动删除满意套装记录</li>
 * </ul>
 *
 * <p>设计文档 §3.3.1 ⑨A/⑨B + §3.3.4 + §3.16.2
 */
public interface IAiOutfitRecordService extends IService<AiOutfitRecord> {

    /**
     * 入库满意套装（Python ai-outfit 调用）
     *
     * <p>Python 在用户选 [满意-加购整套] 或 [满意-下单整套] 时调用。
     * 内部会校验 taskId 归属 + acceptedAction 合法性。
     *
     * @param dto 入库请求（含 taskId/userId/outfitJson/vtonResultUrl/acceptedAction）
     * @return 新建记录的 DTO（含 id）
     */
    AiOutfitRecordDTO createRecord(AiOutfitRecordCreateDTO dto);

    /**
     * 查询当前用户的满意搭配历史列表
     *
     * @param accepted 可选过滤：1=仅满意套装，null=全部
     * @return 按创建时间倒序的记录列表（最多 200 条）
     */
    List<AiOutfitRecordDTO> queryMyRecords(Integer accepted);

    /**
     * 查询单条记录详情
     *
     * @param id 记录ID
     * @return 记录 DTO；不存在或无权查看时返回 null
     */
    AiOutfitRecordDTO queryById(Long id);

    /**
     * 按 taskId + outfitIndex 查询单条记录（Python ai-outfit 内部调用）
     *
     * <p>用途：Redis 任务状态过期后，Python /accept 接口从 DB 兜底读取搭配详情。
     * 内部调用（UserContext.getUser() 为空）允许跨用户查询；用户端调用需校验归属。
     *
     * @param taskId      VTON 任务 ID
     * @param outfitIndex 搭配索引（0/1/2）
     * @return 记录 DTO；不存在时返回 null
     */
    AiOutfitRecordDTO queryByTaskAndIndex(String taskId, Integer outfitIndex);

    /**
     * 删除记录（仅本人可删）
     *
     * @param id 记录ID
     */
    void deleteRecord(Long id);

    /**
     * 查询用户搭配历史（合并 ai_task + ai_outfit_record，按 tab 分组）
     *
     * @param tab 分组: all/processing/accepted/unaccepted/rejected/failed
     * @return 历史记录列表（按创建时间倒序，最多 200 条）
     */
    List<AiOutfitHistoryDTO> queryMyHistory(String tab);

    /**
     * 取消满意联动删除衣橱条目（按 taskId + outfitIndex，仅本人）
     *
     * <p>结果页"满意后又点不满意/取消满意"时调用：查 ai_outfit_record 得到 recordId，
     * 再调 user-service 删除 user_wardrobe 中对应条目（item_type=4）。
     *
     * @param taskId      VTON 任务 ID
     * @param outfitIndex 搭配索引（0/1/2）
     */
    void removeWardrobeByTask(String taskId, Integer outfitIndex);

    /**
     * 订单创建成功后标记搭配记录为"已下单"（trade-service 下单成功回调）
     *
     * <p>置 accepted=1 + acceptedAction=order + orderId，并保存下单前状态快照
     * （prevAccepted/prevAcceptedAction，订单取消/超时回退用），同时联动写衣橱。
     * 幂等：同一 orderId 重复回调跳过。
     *
     * @param recordId    记录ID（可选；为空时按 taskId + outfitIndex 定位）
     * @param taskId      VTON 任务ID（recordId 为空时使用）
     * @param outfitIndex 搭配索引（recordId 为空时使用）
     * @param orderId     订单ID
     * @param userId      下单用户ID（归属校验；为空表示内部调用不校验）
     */
    void markOutfitOrdered(Long recordId, String taskId, Integer outfitIndex, Long orderId, Long userId);

    /**
     * 订单取消/超时未支付时回退搭配记录"已下单"状态（trade-service 取消订单回调）
     *
     * <p>恢复下单前的 accepted/action，清空 orderId 及快照；若回退后非满意（accepted!=1）
     * 则联动删除衣橱条目。按 orderId 反查 ai_outfit_record。
     *
     * @param orderId 订单ID
     * @param userId  下单用户ID（归属校验；为空表示内部调用不校验）
     */
    void revertOutfitOrder(Long orderId, Long userId);
}
