package com.hmall.common.config;

import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import springfox.documentation.swagger2.annotations.EnableSwagger2WebMvc;

@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
@EnableSwagger2WebMvc
public class SwaggerConfig {
}
