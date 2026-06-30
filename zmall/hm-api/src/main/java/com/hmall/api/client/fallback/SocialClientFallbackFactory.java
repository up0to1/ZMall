package com.hmall.api.client.fallback;

import com.hmall.api.client.SocialClient;
import com.hmall.api.vo.FansVO;
import com.hmall.api.vo.FeedVO;
import com.hmall.api.vo.CommentVO;
import com.hmall.api.vo.CommentStatsVO;
import com.hmall.api.dto.*;
import com.hmall.common.domain.PageDTO;
import com.hmall.common.exception.BizIllegalException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cloud.openfeign.FallbackFactory;

@Slf4j
public class SocialClientFallbackFactory implements FallbackFactory<SocialClient> {

    @Override
    public SocialClient create(Throwable cause) {
        return new SocialClient() {
            @Override
            public PageDTO<FansVO> queryFansPage(int page, int size) {
                log.error("远程调用SocialClient#queryFansPage方法出现异常", cause);
                return new PageDTO<>();
            }

            @Override
            public FansStatsDTO getFansStats() {
                log.error("远程调用SocialClient#getFansStats方法出现异常", cause);
                return new FansStatsDTO();
            }

            @Override
            public void deleteFeed(Long feedId) {
                log.error("远程调用SocialClient#deleteFeed方法出现异常，参数：feedId={}", feedId, cause);
                throw new BizIllegalException("社交服务不可用，删除动态失败", cause);
            }

            @Override
            public PageDTO<FeedVO> queryFeedPage(int page, int size) {
                log.error("远程调用SocialClient#queryFeedPage方法出现异常", cause);
                return new PageDTO<>();
            }

            @Override
            public Long publishFeed(ShopFeedDTO feedDTO) {
                log.error("远程调用SocialClient#publishFeed方法出现异常", cause);
                throw new BizIllegalException("社交服务不可用，发布动态失败", cause);
            }

            @Override
            public PageDTO<CommentVO> queryCommentPage(int page, int size) {
                log.error("远程调用SocialClient#queryCommentPage方法出现异常", cause);
                return new PageDTO<>();
            }

            @Override
            public void replyComment(Long id, CommentReplyDTO dto) {
                log.error("远程调用SocialClient#replyComment方法出现异常，参数：id={}", id, cause);
                throw new BizIllegalException("社交服务不可用，回复评价失败", cause);
            }

            @Override
            public void hideComment(Long id) {
                log.error("远程调用SocialClient#hideComment方法出现异常，参数：id={}", id, cause);
                throw new BizIllegalException("社交服务不可用，隐藏评价失败", cause);
            }

            @Override
            public void showComment(Long id) {
                log.error("远程调用SocialClient#showComment方法出现异常，参数：id={}", id, cause);
                throw new BizIllegalException("社交服务不可用，显示评价失败", cause);
            }

            @Override
            public CommentStatsVO getCommentStats() {
                log.error("远程调用SocialClient#getCommentStats方法出现异常", cause);
                return new CommentStatsVO();
            }
        };
    }
}
