package com.hmall.common.hotkey;

import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.beans.factory.support.BeanDefinitionBuilder;
import org.springframework.beans.factory.support.BeanDefinitionRegistry;
import org.springframework.context.annotation.ImportBeanDefinitionRegistrar;
import org.springframework.core.type.AnnotationMetadata;

/**
 * 延迟注册所有热点缓存相关Bean，避免Spring内省时触发类加载失败。
 * 所有Bean均通过字符串类名注册，不直接引用HotKeyCacheAspect等类。
 */
public class HotKeyRegistrar implements ImportBeanDefinitionRegistrar {

    @Override
    public void registerBeanDefinitions(AnnotationMetadata metadata, BeanDefinitionRegistry registry) {
        // 注册 HotKeyProperties
        if (!registry.containsBeanDefinition("com.hmall.common.hotkey.HotKeyProperties")) {
            BeanDefinition propsBd = BeanDefinitionBuilder
                    .genericBeanDefinition("com.hmall.common.hotkey.HotKeyProperties")
                    .getBeanDefinition();
            registry.registerBeanDefinition("com.hmall.common.hotkey.HotKeyProperties", propsBd);
        }

        // 注册 HotKeyDetectTask
        if (!registry.containsBeanDefinition("hotKeyDetectTask")) {
            BeanDefinition detectBd = BeanDefinitionBuilder
                    .genericBeanDefinition("com.hmall.common.hotkey.HotKeyDetectTask")
                    .addConstructorArgReference("stringRedisTemplate")
                    .addConstructorArgReference("com.hmall.common.hotkey.HotKeyProperties")
                    .getBeanDefinition();
            registry.registerBeanDefinition("hotKeyDetectTask", detectBd);
        }

        // 检查AspectJ是否可用，可用才注册切面
        try {
            Class.forName("org.aspectj.lang.ProceedingJoinPoint");
        } catch (ClassNotFoundException e) {
            return;
        }
        if (!registry.containsBeanDefinition("hotKeyCacheAspect")) {
            BeanDefinition aspectBd = BeanDefinitionBuilder
                    .genericBeanDefinition("com.hmall.common.hotkey.HotKeyCacheAspect")
                    .addConstructorArgReference("stringRedisTemplate")
                    .getBeanDefinition();
            registry.registerBeanDefinition("hotKeyCacheAspect", aspectBd);
        }
    }
}
