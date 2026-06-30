package com.hmall.social.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.hmall.social.domain.po.Comment;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface CommentMapper extends BaseMapper<Comment> {
}