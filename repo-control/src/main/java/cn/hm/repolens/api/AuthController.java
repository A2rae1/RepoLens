package cn.hm.repolens.api;
import cn.hm.repolens.domain.*;
import cn.hm.repolens.domain.Rows.User;
import cn.hm.repolens.persistence.ControlMapper;
import cn.hm.repolens.security.AdmissionGate;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.time.Instant;
import java.util.*;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.web.bind.annotation.*;
@RestController @RequestMapping("/api")
public class AuthController {
 private final ControlMapper db;private final AdmissionGate gate;private final PasswordEncoder passwords;private final JwtEncoder encoder;
 public AuthController(ControlMapper db,AdmissionGate gate,PasswordEncoder passwords,JwtEncoder encoder){this.db=db;this.gate=gate;this.passwords=passwords;this.encoder=encoder;}
    public record Login(@NotBlank @Size(max=80) String username,@NotBlank @Size(max=200) String password) {}
    @PostMapping("/auth/login") public Map<String,Object> login(@Valid @RequestBody Login body,jakarta.servlet.http.HttpServletRequest request) {
        gate.check("login-ip:"+request.getRemoteAddr(),30,60000);
        User u=db.user(body.username());
        if(u==null || !passwords.matches(body.password(),u.passwordHash())) throw new DomainException(401,"LOGIN_FAILED","账号或密码不正确");
        Instant now=Instant.now();
        JwtClaimsSet claims=JwtClaimsSet.builder().issuer("repolens").subject(u.id()).issuedAt(now).expiresAt(now.plusSeconds(3600)).claim("roles",List.of(u.role())).build();
        String jwt=encoder.encode(JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(),claims)).getTokenValue();
        return Map.of("accessToken",jwt,"expiresIn",3600,"user",u.id(),"role",u.role());
    }
}
