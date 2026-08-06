package com.hmall.user.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.user.domain.po.Wardrobe;
import com.hmall.user.mapper.WardrobeMapper;
import com.hmall.user.service.IWardrobeService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

/**
 * <p>
 * 我的衣橱 服务实现类
 * </p>
 *
 * @author hmall
 * @since 2026-07-18
 */
@Slf4j
@Service
public class WardrobeServiceImpl extends ServiceImpl<WardrobeMapper, Wardrobe> implements IWardrobeService {

}
