package com.hmall.common.domain;


import com.hmall.common.utils.CollUtils;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class PageDTO<T> {
    protected Long total;
    protected Long pages;
    protected List<T> list;

    public static <T> PageDTO<T> empty(Long total, Long pages) {
        return new PageDTO<>(total, pages, CollUtils.emptyList());
    }

    public static <T> PageDTO<T> of(long total, long pages, List<T> list) {
        return new PageDTO<>(total, pages, list);
    }
}
