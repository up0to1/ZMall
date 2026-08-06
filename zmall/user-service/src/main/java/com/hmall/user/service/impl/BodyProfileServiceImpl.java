package com.hmall.user.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.user.domain.po.BodyProfile;
import com.hmall.user.mapper.BodyProfileMapper;
import com.hmall.user.service.IBodyProfileService;
import org.springframework.stereotype.Service;

/**
 * <p>
 * 用户身体信息档案 服务实现类
 * </p>
 *
 * @author hmall
 * @since 2026-07-27
 */
@Service
public class BodyProfileServiceImpl extends ServiceImpl<BodyProfileMapper, BodyProfile> implements IBodyProfileService {
}
