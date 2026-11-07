package cn.hm.repolens.security;

import cn.hm.repolens.domain.DomainException;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

@Component
public class AdmissionGate {
    private final StringRedisTemplate redis; private final boolean enabled;
    private static final DefaultRedisScript<Long> BUCKET=new DefaultRedisScript<>("""
        local current=redis.call('INCR',KEYS[1])
        if current==1 then redis.call('PEXPIRE',KEYS[1],ARGV[2]) end
        if current>tonumber(ARGV[1]) then return 0 end
        return 1
        """,Long.class);
    public AdmissionGate(StringRedisTemplate redis,@Value("${app.redis-enabled:true}") boolean enabled) { this.redis=redis; this.enabled=enabled; }
    public void check(String dimension,int limit,int windowMs) {
        if(!enabled) return;
        // Admission fails closed when Redis is unavailable. Read APIs still function from DB.
        try {
            if(!Long.valueOf(1).equals(redis.execute(BUCKET,List.of("admission:"+dimension),String.valueOf(limit),String.valueOf(windowMs))))
                throw new DomainException(429,"RATE_LIMITED","请求过于频繁，请稍后重试");
        } catch(DomainException ex) { throw ex; }
        catch(Exception ex) { throw new DomainException(503,"ADMISSION_UNAVAILABLE","准入服务暂不可用，请稍后重试"); }
    }
}
