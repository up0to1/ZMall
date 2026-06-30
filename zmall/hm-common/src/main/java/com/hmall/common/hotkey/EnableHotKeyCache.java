package com.hmall.common.hotkey;

import org.springframework.context.annotation.Import;
import org.springframework.scheduling.annotation.EnableScheduling;

import java.lang.annotation.*;

/**
 * 启用热点Key自动缓存功能。
 * 加在启动类上即可启用AOP切面缓存和定时检测任务。
 * 需要配合 hm.hotkey.enabled=true 配置项。
 */
@Target(ElementType.TYPE)
@Retention(RetentionPolicy.RUNTIME)
@Documented
@EnableScheduling
@Import(HotKeyRegistrar.class)
public @interface EnableHotKeyCache {
}
