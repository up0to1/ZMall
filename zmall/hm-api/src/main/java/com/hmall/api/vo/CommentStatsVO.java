package com.hmall.api.vo;

import lombok.Data;

@Data
public class CommentStatsVO {
    private long totalComments;
    private long todayNew;
    private double avgRating;
    private long pendingReply;
}
