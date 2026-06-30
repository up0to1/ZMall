package com.hmall.user.service.impl;

import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.hmall.common.exception.BadRequestException;
import com.hmall.common.exception.BizIllegalException;
import com.hmall.common.exception.ForbiddenException;
import com.hmall.common.utils.UserContext;

import com.hmall.common.config.JwtProperties;
import com.hmall.common.config.JwtTool;
import com.hmall.user.domain.dto.LoginFormDTO;
import com.hmall.user.domain.dto.RegisterFormDTO;
import com.hmall.user.domain.po.User;
import com.hmall.user.domain.vo.UserLoginVO;
import com.hmall.user.enums.UserStatus;

import java.time.LocalDateTime;
import com.hmall.user.mapper.UserMapper;
import com.hmall.user.service.IUserService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.util.Assert;

/**
 * <p>
 * 用户表 服务实现类
 * </p>
 *
 * @author 虎哥
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements IUserService {

    private final PasswordEncoder passwordEncoder;

    private final JwtTool jwtTool;

    private final JwtProperties jwtProperties;

    @Override
    public UserLoginVO login(LoginFormDTO loginDTO) {
        // 1.数据校验
        String username = loginDTO.getUsername();
        String password = loginDTO.getPassword();
        // 2.根据用户名或手机号查询
        User user = lambdaQuery().eq(User::getUsername, username).one();
        Assert.notNull(user, "用户名错误");
        // 3.校验是否禁用
        if (user.getStatus() == UserStatus.FROZEN) {
            throw new ForbiddenException("用户被冻结");
        }
        // 4.校验密码
        if (!passwordEncoder.matches(password, user.getPassword())) {
            throw new BadRequestException("用户名或密码错误");
        }
        // 5.生成TOKEN
        String token = jwtTool.createToken(user.getId(), user.getRole(), jwtProperties.getTokenTTL());
        // 6.封装VO返回
        UserLoginVO vo = new UserLoginVO();
        vo.setId(user.getId());
        vo.setUserId(user.getId());
        vo.setUsername(user.getUsername());
        vo.setBalance(user.getBalance());
        vo.setRole(user.getRole());
        vo.setToken(token);
        return vo;
    }

    @Override
    public void deductMoney(String pw, Integer totalFee) {
        log.info("开始扣款");
        // 1.校验密码
        User user = getById(UserContext.getUser());
        if(user == null || !passwordEncoder.matches(pw, user.getPassword())){
            // 密码错误
            throw new BizIllegalException("用户密码错误");
        }

        // 2.尝试扣款
        int rows = baseMapper.updateMoney(UserContext.getUser(), totalFee);
        if (rows == 0) {
            throw new BizIllegalException("扣款失败，余额不足！");
        }
        log.info("扣款成功");
    }

    @Override
    public UserLoginVO register(RegisterFormDTO registerFormDTO) {
        // 1.校验用户名是否已存在
        User existUser = lambdaQuery().eq(User::getUsername, registerFormDTO.getUsername()).one();
        if (existUser != null) {
            throw new BadRequestException("用户名已存在");
        }

        // 2.校验角色值
        Integer role = registerFormDTO.getRole();
        if (role == null || (role != 1 && role != 2)) {
            throw new BadRequestException("角色类型错误，只能为1(普通用户)或2(商家)");
        }

        // 3.构建用户对象
        User user = new User();
        user.setUsername(registerFormDTO.getUsername());
        user.setPassword(passwordEncoder.encode(registerFormDTO.getPassword()));
        user.setPhone(registerFormDTO.getPhone());
        user.setStatus(UserStatus.NORMAL);
        user.setBalance(0);
        user.setRole(role);
        user.setCreateTime(LocalDateTime.now());
        user.setUpdateTime(LocalDateTime.now());

        // 4.保存
        save(user);
        log.info("用户注册成功: username={}, role={}", user.getUsername(), role);

        // 5.生成TOKEN，自动登录
        String token = jwtTool.createToken(user.getId(), user.getRole(), jwtProperties.getTokenTTL());
        UserLoginVO vo = new UserLoginVO();
        vo.setId(user.getId());
        vo.setUserId(user.getId());
        vo.setUsername(user.getUsername());
        vo.setBalance(user.getBalance());
        vo.setRole(user.getRole());
        vo.setToken(token);
        return vo;
    }

    @Override
    public void changePassword(String oldPassword, String newPassword) {
        Long userId = UserContext.getUser();
        User user = getById(userId);
        Assert.notNull(user, "用户不存在");
        if (!passwordEncoder.matches(oldPassword, user.getPassword())) {
            throw new BadRequestException("原密码错误");
        }
        user.setPassword(passwordEncoder.encode(newPassword));
        updateById(user);
        log.info("用户修改密码成功: userId={}", userId);
    }
}
