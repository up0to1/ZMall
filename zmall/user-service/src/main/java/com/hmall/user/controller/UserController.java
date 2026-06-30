package com.hmall.user.controller;


import com.hmall.api.dto.DeductMoneyDTO;
import com.hmall.common.utils.BeanUtils;
import com.hmall.common.utils.UserContext;
import com.hmall.user.domain.dto.ChangePasswordDTO;
import com.hmall.user.domain.dto.LoginFormDTO;
import com.hmall.user.domain.dto.RegisterFormDTO;
import com.hmall.user.domain.dto.UserUpdateDTO;
import com.hmall.user.domain.po.User;
import com.hmall.user.domain.vo.UserLoginVO;
import com.hmall.user.service.IUserService;
import io.swagger.annotations.Api;
import io.swagger.annotations.ApiOperation;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@Api(tags = "用户相关接口")
@RestController
@RequestMapping("/users")
@RequiredArgsConstructor
public class UserController {

    private final IUserService userService;

    @ApiOperation("用户登录接口")
    @PostMapping("login")
    public UserLoginVO login(@RequestBody @Validated LoginFormDTO loginFormDTO){
        return userService.login(loginFormDTO);
    }

    @ApiOperation("扣减余额")
    @PutMapping("/money/deduct")
    public void deductMoney(@RequestBody DeductMoneyDTO dto){
        userService.deductMoney(dto.getPw(), dto.getAmount());
    }

    @ApiOperation("用户注册接口")
    @PostMapping("register")
    public UserLoginVO register(@RequestBody @Validated RegisterFormDTO registerFormDTO){
        return userService.register(registerFormDTO);
    }

    @ApiOperation("修改密码")
    @PutMapping("/password")
    public void changePassword(@RequestBody ChangePasswordDTO dto){
        userService.changePassword(dto.getOldPassword(), dto.getNewPassword());
    }

    @ApiOperation("验证商家token有效性（供Nginx auth_request调用）")
    @GetMapping("/verify")
    public void verifyMerchant(){
        // 如果请求能到达这里，说明Gateway已验证token有效且角色为商家
        // 只需返回200即可
    }

    @ApiOperation("查询当前用户信息")
    @GetMapping("/me")
    public UserLoginVO getUserInfo() {
        Long userId = UserContext.getUser();
        User user = userService.getById(userId);
        UserLoginVO vo = new UserLoginVO();
        vo.setId(user.getId());
        vo.setUsername(user.getUsername());
        vo.setPhone(user.getPhone());
        vo.setRole(user.getRole());
        vo.setBalance(user.getBalance());
        return vo;
    }

    @ApiOperation("修改用户信息")
    @PutMapping("/me")
    public void updateUserInfo(@RequestBody UserUpdateDTO dto) {
        Long userId = UserContext.getUser();
        User user = new User();
        user.setId(userId);
        user.setPhone(dto.getPhone());
        userService.updateById(user);
    }

    @ApiOperation("余额充值（模拟）")
    @PostMapping("/recharge")
    public void recharge(@RequestBody java.util.Map<String, Integer> params) {
        Long userId = UserContext.getUser();
        Integer amount = params.get("amount");
        if (amount == null || amount <= 0) {
            throw new IllegalArgumentException("充值金额必须大于0");
        }
        User user = userService.getById(userId);
        user.setBalance(user.getBalance() + amount);
        userService.updateById(user);
    }

    @ApiOperation("退款到余额（供微服务内部调用）")
    @PutMapping("/money/refund")
    public void refundMoney(@RequestParam("userId") Long userId, @RequestParam("amount") Integer amount) {
        if (userId == null || amount == null || amount <= 0) {
            throw new IllegalArgumentException("参数无效");
        }
        User user = userService.getById(userId);
        if (user == null) {
            throw new IllegalArgumentException("用户不存在");
        }
        user.setBalance(user.getBalance() + amount);
        userService.updateById(user);
    }
}
