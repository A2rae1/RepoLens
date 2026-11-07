package cn.hm.repolens;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import com.nimbusds.jose.jwk.source.ImmutableSecret;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import javax.crypto.spec.SecretKeySpec;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(properties={"app.demo-users=true","app.demo-password=fixture-repolens-password"})
@ActiveProfiles("test") @AutoConfigureMockMvc
class AuthenticationBoundaryTest {
 @Autowired MockMvc web;
 @Test void ownLoginAndStandalonePageWorkWithoutEventService()throws Exception{
  web.perform(post("/api/auth/login").contentType("application/json").content("{\"username\":\"alice\",\"password\":\"fixture-repolens-password\"}"))
   .andExpect(status().isOk()).andExpect(jsonPath("$.accessToken").exists()).andExpect(jsonPath("$.role").value("RESEARCHER"));
  web.perform(get("/index.html")).andExpect(status().isOk()).andExpect(content().string(org.hamcrest.Matchers.containsString("RepoLens")));
  web.perform(get("/api/agent/jobs")).andExpect(status().isUnauthorized());
 }
 @Test void eventIssuerIsRejectedEvenWithTheSameTestSigningKey()throws Exception{
  var key=new SecretKeySpec("test-repolens-0123456789abcdef0123456789".getBytes(StandardCharsets.UTF_8),"HmacSHA256");
  JwtEncoder signer=new NimbusJwtEncoder(new ImmutableSecret<>(key));
  var claims=JwtClaimsSet.builder().issuer("event-fulfill").subject("alice").issuedAt(Instant.now()).expiresAt(Instant.now().plusSeconds(60)).claim("roles",List.of("RESEARCHER")).build();
  String token=signer.encode(JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(),claims)).getTokenValue();
  web.perform(get("/api/agent/jobs").header("Authorization","Bearer "+token)).andExpect(status().isUnauthorized());
 }
}
