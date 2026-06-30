package com.hmall.social.service.impl;

import cn.hutool.core.util.StrUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmall.common.domain.PageDTO;
import com.hmall.api.dto.CommentCreateDTO;
import com.hmall.api.dto.CommentReplyDTO;
import com.hmall.api.dto.ItemDTO;
import com.hmall.api.client.ItemClient;
import com.hmall.api.vo.CommentStatsVO;
import com.hmall.api.vo.CommentVO;
import com.hmall.common.exception.BadRequestException;
import com.hmall.social.domain.po.Comment;
import com.hmall.social.mapper.CommentMapper;
import com.hmall.social.service.ICommentService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

@Slf4j
@Service
@RequiredArgsConstructor
public class CommentServiceImpl implements ICommentService {

    private final CommentMapper commentMapper;
    private final ItemClient itemClient;
    private static final DateTimeFormatter FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void createComment(Long userId, CommentCreateDTO dto) {
        Comment comment = new Comment();
        comment.setItemId(dto.getItemId());
        comment.setOrderId(dto.getOrderId());
        comment.setUserId(userId);
        comment.setContent(dto.getContent());
        comment.setRating(dto.getRating() != null ? dto.getRating() : 5);
        comment.setImages(dto.getImages());
        comment.setIsHidden(0);
        commentMapper.insert(comment);
        log.info("用户评价提交成功: userId={}, itemId={}, orderId={}", userId, dto.getItemId(), dto.getOrderId());
    }

    @Override
    public PageDTO<CommentVO> queryCommentsByItem(Long itemId, int page, int size) {
        LambdaQueryWrapper<Comment> wrapper = new LambdaQueryWrapper<Comment>()
                .eq(Comment::getItemId, itemId)
                .eq(Comment::getIsHidden, 0)
                .orderByDesc(Comment::getCreateTime);
        Page<Comment> commentPage = commentMapper.selectPage(new Page<>(page, size), wrapper);
        return toVOPage(commentPage);
    }

    @Override
    public PageDTO<CommentVO> queryAllComments(int page, int size, String content) {
        LambdaQueryWrapper<Comment> wrapper = new LambdaQueryWrapper<Comment>()
                .like(StrUtil.isNotBlank(content), Comment::getContent, content)
                .orderByDesc(Comment::getCreateTime);
        Page<Comment> commentPage = commentMapper.selectPage(new Page<>(page, size), wrapper);
        return toVOPage(commentPage);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void replyComment(Long commentId, CommentReplyDTO dto) {
        Comment comment = commentMapper.selectById(commentId);
        if (comment == null) {
            throw new BadRequestException("评价不存在");
        }
        comment.setReply(dto.getReply());
        comment.setReplyTime(LocalDateTime.now());
        commentMapper.updateById(comment);
        log.info("商家回复评价: commentId={}", commentId);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void hideComment(Long commentId) {
        Comment comment = commentMapper.selectById(commentId);
        if (comment == null) {
            throw new BadRequestException("评价不存在");
        }
        comment.setIsHidden(1);
        commentMapper.updateById(comment);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public void showComment(Long commentId) {
        Comment comment = commentMapper.selectById(commentId);
        if (comment == null) {
            throw new BadRequestException("评价不存在");
        }
        comment.setIsHidden(0);
        commentMapper.updateById(comment);
    }

    @Override
    public CommentStatsVO getCommentStats() {
        LocalDateTime todayStart = LocalDateTime.of(LocalDate.now(), LocalTime.MIN);
        CommentStatsVO stats = new CommentStatsVO();
        stats.setTotalComments(commentMapper.selectCount(null));
        stats.setTodayNew(commentMapper.selectCount(
                new LambdaQueryWrapper<Comment>().ge(Comment::getCreateTime, todayStart)));
        stats.setPendingReply(commentMapper.selectCount(
                new LambdaQueryWrapper<Comment>().isNull(Comment::getReply)));

        // 计算平均评分
        List<Comment> allComments = commentMapper.selectList(null);
        if (allComments != null && !allComments.isEmpty()) {
            double avg = allComments.stream()
                    .mapToInt(c -> c.getRating() != null ? c.getRating() : 5)
                    .average().orElse(5.0);
            stats.setAvgRating(Math.round(avg * 10.0) / 10.0);
        } else {
            stats.setAvgRating(5.0);
        }
        return stats;
    }

    private PageDTO<CommentVO> toVOPage(Page<Comment> commentPage) {
        List<Comment> records = commentPage.getRecords();
        // 批量查询商品名称
        Set<Long> itemIds = records.stream()
                .map(Comment::getItemId)
                .filter(id -> id != null)
                .collect(Collectors.toSet());
        Map<Long, String> itemNameMap = Map.of();
        if (!itemIds.isEmpty()) {
            try {
                List<ItemDTO> items = itemClient.queryItemByIds(itemIds);
                if (items != null) {
                    itemNameMap = items.stream()
                            .collect(Collectors.toMap(ItemDTO::getId, ItemDTO::getName, (a, b) -> a));
                }
            } catch (Exception e) {
                log.warn("查询商品名称失败", e);
            }
        }
        Map<Long, String> finalItemNameMap = itemNameMap;
        List<CommentVO> list = records.stream().map(c -> {
            CommentVO vo = new CommentVO();
            vo.setId(c.getId());
            vo.setItemId(c.getItemId());
            vo.setItemName(finalItemNameMap.getOrDefault(c.getItemId(), "未知商品"));
            vo.setOrderId(c.getOrderId());
            vo.setUserId(c.getUserId());
            vo.setContent(c.getContent());
            vo.setRating(c.getRating());
            vo.setImages(c.getImages());
            vo.setReply(c.getReply());
            vo.setReplyTime(c.getReplyTime() != null ? c.getReplyTime().format(FORMATTER) : null);
            vo.setIsHidden(c.getIsHidden());
            vo.setCreateTime(c.getCreateTime() != null ? c.getCreateTime().format(FORMATTER) : null);
            return vo;
        }).collect(Collectors.toList());
        return PageDTO.of(commentPage.getTotal(), commentPage.getPages(), list);
    }
}