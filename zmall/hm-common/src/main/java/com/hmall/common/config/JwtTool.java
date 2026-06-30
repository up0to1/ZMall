package com.hmall.common.config;

import cn.hutool.core.exceptions.ValidateException;
import cn.hutool.jwt.JWT;
import cn.hutool.jwt.JWTValidator;
import cn.hutool.jwt.signers.JWTSigner;
import cn.hutool.jwt.signers.JWTSignerUtil;
import com.hmall.common.exception.UnauthorizedException;

import java.security.KeyPair;
import java.time.Duration;
import java.util.Date;

public class JwtTool {
    private final JWTSigner jwtSigner;

    public JwtTool(KeyPair keyPair) {
        this.jwtSigner = JWTSignerUtil.createSigner("rs256", keyPair);
    }

    /**
     * 创建 access-token
     * @param userId 用户ID
     * @param role 用户角色：1-普通用户 2-商家管理员
     * @param ttl 有效期
     * @return token字符串
     */
    public String createToken(Long userId, Integer role, Duration ttl) {
        return JWT.create()
                .setPayload("user", userId)
                .setPayload("role", role != null ? role : 1)
                .setExpiresAt(new Date(System.currentTimeMillis() + ttl.toMillis()))
                .setSigner(jwtSigner)
                .sign();
    }

    /**
     * 创建 access-token（默认角色为普通用户）
     */
    public String createToken(Long userId, Duration ttl) {
        return createToken(userId, 1, ttl);
    }

    /**
     * 解析token
     * @param token token
     * @return 用户ID
     */
    public Long parseToken(String token) {
        if (token == null) {
            throw new UnauthorizedException("未登录");
        }
        JWT jwt;
        try {
            jwt = JWT.of(token).setSigner(jwtSigner);
        } catch (Exception e) {
            throw new UnauthorizedException("无效的token", e);
        }
        if (!jwt.verify()) {
            throw new UnauthorizedException("无效的token");
        }
        try {
            JWTValidator.of(jwt).validateDate();
        } catch (ValidateException e) {
            throw new UnauthorizedException("token已经过期");
        }
        Object userPayload = jwt.getPayload("user");
        if (userPayload == null) {
            throw new UnauthorizedException("无效的token");
        }
        try {
            return Long.valueOf(userPayload.toString());
        } catch (RuntimeException e) {
            throw new UnauthorizedException("无效的token");
        }
    }

    /**
     * 解析token中的角色信息
     * @param token token
     * @return 角色ID，默认为1（普通用户）
     */
    public Integer parseRole(String token) {
        if (token == null) {
            return 1;
        }
        try {
            JWT jwt = JWT.of(token).setSigner(jwtSigner);
            Object rolePayload = jwt.getPayload("role");
            if (rolePayload == null) {
                return 1;
            }
            return Integer.valueOf(rolePayload.toString());
        } catch (Exception e) {
            return 1;
        }
    }
}
