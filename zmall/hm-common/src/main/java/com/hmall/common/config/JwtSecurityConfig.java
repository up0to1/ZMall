package com.hmall.common.config;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.rsa.crypto.KeyStoreKeyFactory;

import java.security.KeyPair;

@Configuration
@ConditionalOnProperty(name = "hm.jwt.location")
@EnableConfigurationProperties(JwtProperties.class)
public class JwtSecurityConfig {

    @Bean
    public KeyPair keyPair(JwtProperties properties) {
        KeyStoreKeyFactory keyStoreKeyFactory =
                new KeyStoreKeyFactory(
                        properties.getLocation(),
                        properties.getPassword().toCharArray());
        return keyStoreKeyFactory.getKeyPair(
                properties.getAlias(),
                properties.getPassword().toCharArray());
    }

    @Bean
    public JwtTool jwtTool(KeyPair keyPair) {
        return new JwtTool(keyPair);
    }
}
