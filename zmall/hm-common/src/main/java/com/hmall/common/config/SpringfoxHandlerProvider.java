package com.hmall.common.config;

import org.springframework.boot.autoconfigure.condition.ConditionalOnClass;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Configuration;

/**
 * Springfox 2.10.5 + Spring Boot 2.7+ 兼容性修复
 *
 * <p>问题：Spring Boot 2.6+ 默认用 PathPatternParser，actuator 端点注册的 mapping
 * 没有 PatternsRequestCondition，Springfox 在 getPatterns() 时 NPE。
 *
 * <p>修复：通过 BeanPostProcessor 替换 WebMvcRequestHandlerProvider 内部的
 * handlerMappings，过滤掉 actuator 的 handler mapping，避免 NPE。
 *
 * <p>仅 Servlet 环境加载（gateway 是 Reactive WebFlux，没有 servlet API，
 * 强加载会因 NoClassDefFoundError 启动失败）。
 *
 * <p>同时需要在 application.yaml 配置 spring.mvc.pathmatch.matching-strategy: ant_path_matcher
 */
@Configuration
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
@ConditionalOnClass(name = "org.springframework.web.servlet.mvc.method.RequestMappingInfoHandlerMapping")
public class SpringfoxHandlerProvider {

    @org.springframework.context.annotation.Bean
    public static org.springframework.beans.factory.config.BeanPostProcessor springfoxHandlerProviderBeanPostProcessor() {
        return new org.springframework.beans.factory.config.BeanPostProcessor() {
            @Override
            public Object postProcessAfterInitialization(Object bean, String beanName) throws org.springframework.beans.BeansException {
                if (bean instanceof springfox.documentation.spring.web.plugins.WebMvcRequestHandlerProvider) {
                    customizeSpringfoxHandlerMappings(getHandlerMappings(bean));
                }
                return bean;
            }

            private <T extends org.springframework.web.servlet.mvc.method.RequestMappingInfoHandlerMapping> void customizeSpringfoxHandlerMappings(java.util.List<T> mappings) {
                java.util.List<T> copy = mappings.stream()
                        .filter(mapping -> mapping.getPatternParser() == null)
                        .collect(java.util.stream.Collectors.toList());
                mappings.clear();
                mappings.addAll(copy);
            }

            @SuppressWarnings("unchecked")
            private java.util.List<org.springframework.web.servlet.mvc.method.RequestMappingInfoHandlerMapping> getHandlerMappings(Object bean) {
                try {
                    java.lang.reflect.Field field = org.springframework.util.ReflectionUtils.findField(bean.getClass(), "handlerMappings");
                    if (field == null) {
                        throw new IllegalStateException("handlerMappings field not found on " + bean.getClass());
                    }
                    field.setAccessible(true);
                    return (java.util.List<org.springframework.web.servlet.mvc.method.RequestMappingInfoHandlerMapping>) field.get(bean);
                } catch (IllegalAccessException | SecurityException e) {
                    throw new IllegalStateException(e);
                }
            }
        };
    }
}
