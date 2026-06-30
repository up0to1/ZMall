package com.hmall.social.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.hmall.api.dto.CommentCreateDTO;
import com.hmall.api.dto.CommentReplyDTO;
import com.hmall.api.vo.CommentStatsVO;
import com.hmall.api.vo.CommentVO;
import com.hmall.common.domain.PageDTO;

public interface ICommentService {

    void createComment(Long userId, CommentCreateDTO dto);

    PageDTO<CommentVO> queryCommentsByItem(Long itemId, int page, int size);

    PageDTO<CommentVO> queryAllComments(int page, int size, String content);

    void replyComment(Long commentId, CommentReplyDTO dto);

    void hideComment(Long commentId);

    void showComment(Long commentId);

    CommentStatsVO getCommentStats();
}
