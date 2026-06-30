package com.hmall.api.config;

import com.hmall.api.client.fallback.*;
import com.hmall.common.utils.UserContext;
import feign.Logger;
import feign.RequestInterceptor;
import feign.RequestTemplate;
import org.springframework.context.annotation.Bean;

public class DefaultFeignConfig {

    @Bean
    public Logger.Level feignLoggerLevel(){
        return Logger.Level.FULL;
    }

    @Bean
    public RequestInterceptor userInfoRequestInterceptor(){
        return new RequestInterceptor() {
            @Override
            public void apply(RequestTemplate template) {
                Long userId = UserContext.getUser();
                if (userId != null){
                    template.header("user-info", userId.toString());
                }
            }
        };
    }

    @Bean
    public ItemClientFallbackFactory itemClientFallbackFactory(){
        return new ItemClientFallbackFactory();
    }

    @Bean
    public CartClientFallbackFactory cartClientFallbackFactory(){
        return new CartClientFallbackFactory();
    }

    @Bean
    public UserClientFallbackFactory userClientFallbackFactory(){
        return new UserClientFallbackFactory();
    }

    @Bean
    public PayClientFallbackFactory payClientFallbackFactory(){
        return new PayClientFallbackFactory();
    }

    @Bean
    public TradeClientFallbackFactory tradeClientFallbackFactory(){
        return new TradeClientFallbackFactory();
    }

    @Bean
    public SocialClientFallbackFactory socialClientFallbackFactory(){
        return new SocialClientFallbackFactory();
    }
}
