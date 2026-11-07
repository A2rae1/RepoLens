package cn.hm.repolens.security;

import cn.hm.repolens.domain.Rows.User;
import cn.hm.repolens.persistence.ControlMapper;
import com.nimbusds.jose.jwk.source.ImmutableSecret;
import java.nio.charset.StandardCharsets;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.*;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.server.resource.authentication.*;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
@EnableMethodSecurity
public class SecurityConfig {
    @Bean PasswordEncoder passwordEncoder() { return new BCryptPasswordEncoder(); }
    @Bean SecretKeySpec signingKey(@Value("${app.jwt-secret}") String secret) {
        if(secret.getBytes(StandardCharsets.UTF_8).length<32) throw new IllegalArgumentException("REPOLENS_JWT_SECRET must contain >=32 bytes");
        return new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8),"HmacSHA256");
    }
    @Bean JwtEncoder jwtEncoder(SecretKeySpec key) { return new NimbusJwtEncoder(new ImmutableSecret<>(key)); }
    @Bean JwtDecoder jwtDecoder(SecretKeySpec key) {
        NimbusJwtDecoder decoder=NimbusJwtDecoder.withSecretKey(key).macAlgorithm(MacAlgorithm.HS256).build();
        decoder.setJwtValidator(JwtValidators.createDefaultWithIssuer("repolens")); return decoder;
    }
    @Bean SecurityFilterChain security(HttpSecurity http) throws Exception {
        JwtGrantedAuthoritiesConverter roles=new JwtGrantedAuthoritiesConverter(); roles.setAuthoritiesClaimName("roles"); roles.setAuthorityPrefix("ROLE_");
        JwtAuthenticationConverter converter=new JwtAuthenticationConverter(); converter.setJwtGrantedAuthoritiesConverter(roles);
        return http.csrf(csrf->csrf.disable())
            .sessionManagement(s->s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(a->a.requestMatchers("/","/index.html","/app.js","/event-stream.js","/style.css","/vendor/**","/favicon.ico","/favicon.svg","/api/auth/login","/actuator/health","/internal/agent-jobs/**").permitAll()
                .requestMatchers("/actuator/**").hasRole("OPERATOR").anyRequest().authenticated())
            .oauth2ResourceServer(o->o.jwt(j->j.jwtAuthenticationConverter(converter))).build();
    }
    @Bean @ConditionalOnProperty(name="app.demo-users",havingValue="true")
    ApplicationRunner demoUsers(ControlMapper db,PasswordEncoder encoder,@Value("${app.demo-password}") String password) {
        return args->{
            if(password.length()<12) throw new IllegalStateException("Demo password must have >=12 characters");
            for(String user:new String[]{"alice","bob","operator"})
                if(db.user(user)==null) db.insertUser(new User(user,encoder.encode(password),user.equals("operator")?"OPERATOR":"RESEARCHER"));
        };
    }
}
