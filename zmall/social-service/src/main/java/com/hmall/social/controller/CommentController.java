package com.hmall.social.controller;

import com.hmall.common.domain.PageDTO;
import com.hmall.api.dto.CommentCreateDTO;
import com.hmall.api.dto.CommentReplyDTO;
import com.hmall.api.vo.CommentStatsVO;
import com.hmall.api.vo.CommentVO;
import com.hmall.common.service.FileStorageStrategy;
import com.hmall.common.utils.UserContext;
import com.hmall.social.service.ICommentService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@Api(tags = "商品评价接口")
@RestController
@RequestMapping("/comments")
@RequiredArgsConstructor
public class CommentController {

    private final ICommentService commentService;

    private final FileStorageStrategy fileStorageStrategy;

    // ========== 前台接口 ==========

    @ApiOperation("用户提交评价")
    @PostMapping
    public void createComment(@RequestBody CommentCreateDTO dto) {
        Long userId = UserContext.getUser();
        commentService.createComment(userId, dto);
    }

    @ApiOperation("查询商品评价列表（前台展示）")
    @GetMapping("/item/{itemId}")
    public PageDTO<CommentVO> queryByItem(
            @PathVariable("itemId") Long itemId,
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size) {
        return commentService.queryCommentsByItem(itemId, page, size);
    }

    // ========== 后台管理接口 ==========

    @ApiOperation("商家后台-查询所有评价")
    @GetMapping("/admin/page")
    public PageDTO<CommentVO> queryAllComments(
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "10") int size,
            @RequestParam(value = "content", required = false) String content) {
        return commentService.queryAllComments(page, size, content);
    }

    @ApiOperation("商家后台-回复评价")
    @PutMapping("/admin/{id}/reply")
    public void replyComment(@PathVariable("id") Long id, @RequestBody CommentReplyDTO dto) {
        commentService.replyComment(id, dto);
    }

    @ApiOperation("商家后台-隐藏评价")
    @PutMapping("/admin/{id}/hide")
    public void hideComment(@PathVariable("id") Long id) {
        commentService.hideComment(id);
    }

    @ApiOperation("商家后台-显示评价")
    @PutMapping("/admin/{id}/show")
    public void showComment(@PathVariable("id") Long id) {
        commentService.showComment(id);
    }

    @ApiOperation("商家后台-评价统计")
    @GetMapping("/admin/stats")
    public CommentStatsVO getCommentStats() {
        return commentService.getCommentStats();
    }

    @ApiOperation("文件上传（评价图片）")
    @PostMapping("/upload")
    public String uploadFile(@RequestParam("file") MultipartFile file) {
        return fileStorageStrategy.upload(file, "comments");
    }
}