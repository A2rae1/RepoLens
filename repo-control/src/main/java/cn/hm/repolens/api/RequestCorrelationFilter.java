package cn.hm.repolens.api;

import cn.hm.repolens.domain.RequestScope;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
public class RequestCorrelationFilter extends OncePerRequestFilter {
    private final String instance=UUID.randomUUID().toString();
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain)throws ServletException,IOException{
        String supplied=request.getHeader("X-Request-Id");
        String id=supplied!=null&&supplied.matches("[a-zA-Z0-9-]{1,80}")?supplied:UUID.randomUUID().toString();
        RequestScope.set(id);MDC.put("requestId",id);response.setHeader("X-Request-Id",id);
        response.setHeader("X-Service-Instance",instance);
        String parent=cn.hm.repolens.domain.TraceContext.parent();if(parent!=null)response.setHeader("X-Trace-Id",parent.split("-")[1]);
        try{chain.doFilter(request,response);}finally{RequestScope.set(null);MDC.remove("requestId");}
    }
}
