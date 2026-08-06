package com.hmall.item.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.hmall.api.dto.AiOutfitHistoryDTO;
import com.hmall.item.domain.po.AiOutfitRecord;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * AI 随心搭效果图入库 Mapper
 */
public interface AiOutfitRecordMapper extends BaseMapper<AiOutfitRecord> {

    /**
     * 查询用户搭配历史（ai_task LEFT JOIN ai_outfit_record）
     *
     * @param userId        用户ID
     * @param tabCondition  分组条件（由 Service 层白名单映射生成，防注入）
     * @return 合并后的历史记录列表（按创建时间倒序，最多 200 条）
     */
    @Select("SELECT " +
            "  r.id AS id, " +
            "  r.task_id AS taskId, " +
            "  COALESCE(t.status, 'SUCCESS') AS taskStatus, " +
            "  COALESCE(t.task_type, 'OUTFIT_AGENT') AS taskType, " +
            "  t.phase AS phase, " +
            "  t.error_msg AS errorMsg, " +
            "  r.outfit_json AS outfitJson, " +
            "  r.vton_result_url AS vtonResultUrl, " +
            "  r.user_photo_url AS userPhotoUrl, " +
            "  r.model_image_source AS modelImageSource, " +
            "  r.accepted AS accepted, " +
            "  r.accepted_action AS acceptedAction, " +
            "  r.credits_consumed AS creditsConsumed, " +
            "  r.round AS round, " +
            "  r.outfit_index AS outfitIndex, " +
            "  r.created_at AS createdAt, " +
            "  t.finished_at AS finishedAt " +
            "FROM ai_outfit_record r " +
            "LEFT JOIN ai_task t ON t.task_id = r.task_id " +
            "WHERE r.user_id = #{userId} " +
            "  ${tabCondition} " +
            "ORDER BY r.created_at DESC " +
            "LIMIT 200")
    List<AiOutfitHistoryDTO> queryMyHistory(
            @Param("userId") Long userId,
            @Param("tabCondition") String tabCondition);
}
