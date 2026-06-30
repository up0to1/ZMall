package com.hmall.social;

import com.hmall.api.config.DefaultFeignConfig;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.openfeign.EnableFeignClients;

@MapperScan("com.hmall.social.mapper")
@SpringBootApplication(scanBasePackages = "com.hmall")
@EnableFeignClients(basePackages = "com.hmall.api.client", defaultConfiguration = DefaultFeignConfig.class)
public class SocialApplication {
    public static void main(String[] args) {
        SpringApplication.run(SocialApplication.class, args);
    }
}