package com.hmall.api.client;


import com.hmall.common.domain.PageDTO;
import com.hmall.api.client.fallback.SocialClientFallbackFactory;
import com.hmall.api.dto.*;
import com.hmall.api.vo.CommentStatsVO;
import com.hmall.api.vo.CommentVO;
import com.hmall.api.vo.FansVO;
import com.hmall.api.vo.FeedVO;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.*;

@FeignClient(value = "social-service", fallbackFactory = SocialClientFallbackFactory.class)
public interface SocialClient {

    @GetMapping("/shop/fans/page")
    PageDTO<FansVO> queryFansPage(
            @RequestParam("page") int page,
            @RequestParam("size") int size);

    @GetMapping("/shop/fans/stats")
    FansStatsDTO getFansStats();

    @DeleteMapping("/shop/feed/{feedId}")
    void deleteFeed(@PathVariable("feedId") Long feedId);

    @GetMapping("/shop/feed/page")
    PageDTO<FeedVO> queryFeedPage(
            @RequestParam("page") int page,
            @RequestParam("size") int size);

    // ========== Feed 发布 ==========

    @PostMapping("/shop/feed")
    Long publishFeed(@RequestBody ShopFeedDTO feedDTO);

    // ========== Comment 评价 ==========

    @GetMapping("/comments/admin/page")
    PageDTO<CommentVO> queryCommentPage(
            @RequestParam("page") int page,
            @RequestParam("size") int size);

    @PutMapping("/comments/admin/{id}/reply")
    void replyComment(@PathVariable("id") Long id, @RequestBody CommentReplyDTO dto);

    @PutMapping("/comments/admin/{id}/hide")
    void hideComment(@PathVariable("id") Long id);

    @PutMapping("/comments/admin/{id}/show")
    void showComment(@PathVariable("id") Long id);

    @GetMapping("/comments/admin/stats")
    CommentStatsVO getCommentStats();
}
