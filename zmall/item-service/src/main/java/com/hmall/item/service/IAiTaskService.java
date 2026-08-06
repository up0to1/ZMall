package com.hmall.item.service;

import com.baomidou.mybatisplus.extension.service.IService;
import com.hmall.api.dto.AiModelGenerateDTO;
import com.hmall.api.dto.AiModelImageFeedbackDTO;
import com.hmall.api.dto.AiModelPublishDTO;
import com.hmall.api.dto.AiModelResultMessage;
import com.hmall.api.dto.AiTaskDTO;
import com.hmall.api.dto.SystemModelImageDTO;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.domain.PageQuery;
import com.hmall.item.domain.po.AiTask;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * AI 任务服务
 *
 * <p>2026-07-19 v2 重构：取消三级模特图池，统一为系统模特图池。
 *
 * <p>职责：
 * <ol>
 *   <li>创建 AI 模特图生成任务（多商品链式 VTON）：写表 + 发 MQ</li>
 *   <li>处理 Python 回流结果（MQ 消费调用）：更新表 + 确认/回滚配额</li>
 *   <li>查询任务状态/列表</li>
 *   <li>商家发布模特图到商品主图（HIL：商家审阅满意后调 publish）</li>
 *   <li>系统模特图池 CRUD（全平台共用，仅创建者可改删）</li>
 * </ol>
 */
public interface IAiTaskService extends IService<AiTask> {

    /**
     * 创建 AI 模特图生成任务
     * 流程：校验商品归属 → 校验品类冲突 → 解析模特图 URL（从系统池）→ 配额预扣 → 写 ai_task → 发 MQ
     */
    AiTaskDTO createModelGenerateTask(AiModelGenerateDTO dto);

    /**
     * 处理 Python 回流结果（MQ 消费调用）
     * 流程：幂等校验 → 更新 ai_task → 配额确认/回滚
     */
    void handleModelResult(AiModelResultMessage message);

    /**
     * 商家发布模特图：写回商品主图字段 + 清缓存
     * 校验：itemId ∈ aiTask.itemIds + imageUrl ∈ aiTask.resultUrls
     */
    void publishModelImage(AiModelPublishDTO dto);

    /**
     * 查询任务详情
     */
    AiTaskDTO queryByTaskId(String taskId);

    /**
     * 查询当前商家的任务列表
     */
    List<AiTaskDTO> queryMyTasks(String status);

    // ========== 系统模特图池 CRUD（全平台共用）==========

    /**
     * 查询系统模特图列表（所有商家都能查 is_active=1 的，按 isDefault 倒序 + 创建时间正序）
     *
     * <p>2026-07-20 新增分页：避免池过大时返回过多数据。
     *
     * @param gender 性别过滤（可空）
     * @param skinTone 肤色过滤（可空）
     * @param currentUserId 当前登录用户（用于标记 mine 字段，前端判断能否编辑/删除）
     * @param pageQuery 分页参数
     */
    PageDTO<SystemModelImageDTO> listSystemModelImages(String gender, String skinTone, Long currentUserId, PageQuery pageQuery);

    /**
     * 上传并创建系统模特图（multipart 上传，自动入池）
     *
     * <p>存储策略：优先 OSS，OSS 未启用则本地存储（{@code zmall-nginx/html/uploads/model-images/}）。
     *
     * @param file 图片文件
     * @param dto 模特图元信息（不含 imageUrl，由上传后自动填充）
     * @param currentUserId 当前登录用户（作为 uploaderUserId）
     * @return 新建记录的 DTO（含 id 和 imageUrl）
     */
    SystemModelImageDTO createSystemModelImage(MultipartFile file, SystemModelImageDTO dto, Long currentUserId);

    /**
     * 修改系统模特图元信息（仅创建者可操作，不含文件更新）
     */
    void updateSystemModelImage(Long id, SystemModelImageDTO dto, Long currentUserId);

    /**
     * 删除系统模特图（软删：is_active=0，仅创建者可操作）
     */
    void deleteSystemModelImage(Long id, Long currentUserId);

    /**
     * 切换系统模特图展示/不展示（仅创建者可操作）
     *
     * <p>展示（is_active=1）：全平台可用，包括 AI 随心搭兜底查询；
     * 不展示（is_active=0）：其他商家和 AI 随心搭都不可用，仅创建者可见。
     *
     * @param id            模特图 ID
     * @param isActive      目标展示状态：1=展示 0=不展示
     * @param currentUserId 当前登录用户 ID（权限校验）
     */
    void updateSystemModelImageVisibility(Long id, Integer isActive, Long currentUserId);

    /**
     * 随机获取一张系统默认模特图（AI 随心搭兜底用：用户无自拍照时使用）
     *
     * <p>优先 is_default=1 的，无则取 is_active=1 的任意一张。
     *
     * @return 模特图 DTO；池为空时返回 null（调用方需进一步兜底，如 AI 生成）
     */
    SystemModelImageDTO getRandomDefaultModelImage();

    // ========== v3 评分与激励（2026-07-20 新增）==========

    /**
     * 商家对 AI 模特生成结果评分（五星 + 标签 + 备注）
     *
     * <p>v3.1 评分规则：
     * <ul>
     *   <li>≥3★ + 商家同意入池 → 最终图自动入 system_model_image 池（source=1）</li>
     *   <li>≥4★ + 后续发布到商品主图 → 发布时奖励 1 credit（每日上限 5 次）</li>
     *   <li>同一任务仅允许评分一次（uk_task_id_type 唯一索引保证）</li>
     * </ul>
     *
     * @param taskId 任务 ID
     * @param starRating 五星评分（1-5）
     * @param ratingTags 评分标签数组（可空，如 ["质感好","比例协调"]）
     * @param ratingNote 评分备注（可空）
     * @param saveToPool 商家是否同意将最终图入系统模特图池（true 时 ≥3★ 自动入池）
     * @return 评分反馈记录 DTO（含 id、awardedCredits、savedToPool 字段）
     */
    AiModelImageFeedbackDTO rateTask(String taskId, Integer starRating,
                                      List<String> ratingTags, String ratingNote,
                                      Boolean saveToPool);

    /**
     * 商家提交拒绝原因（不满意 AI 生成结果时）
     *
     * <p>v3.1 激励规则：
     * <ul>
     *   <li>拒绝原因 ≥20 字 → 奖励 1 credit（每日上限 3 次）</li>
     *   <li>同一任务仅允许拒绝一次（uk_task_id_type 唯一索引保证）</li>
     * </ul>
     *
     * @param taskId 任务 ID
     * @param rejectReason 拒绝原因（必填，≥20 字可奖励 credit）
     * @return 拒绝反馈记录 DTO（含 id、awardedCredits 字段）
     */
    AiModelImageFeedbackDTO rejectTask(String taskId, String rejectReason);

    /**
     * 创建 AI 生成的模特图入库记录（source=3，AI 自动生成专用接口）
     *
     * <p>适用场景：
     * <ul>
     *   <li>AI 随心搭场景 A 兜底：用户无自拍照且系统池为空时，Python 调 Qwen/可灵 AI 生成契合穿搭的模特图</li>
     *   <li>商家 AI 模特任务评分 ≥3★ 时，最终图自动入池（source=1，由 rateTask 内部调用）</li>
     * </ul>
     *
     * @param imageUrl 模特图 URL（相对路径或完整 URL）
     * @param source 来源：1=AI任务后保存（≥3★）/ 3=AI自动生成
     * @param gender 性别（可空）
     * @param skinTone 肤色（可空）
     * @param styleTags 风格标签（可空）
     * @param note 备注（可空）
     * @param uploaderUserId 上传者用户ID（AI 生成时可为空）
     * @return 新建记录的 DTO
     */
    SystemModelImageDTO createAiGeneratedModelImage(String imageUrl, Integer source,
                                                    String gender, String skinTone,
                                                    List<String> styleTags, String note,
                                                    Long uploaderUserId);
}
