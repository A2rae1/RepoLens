package cn.hm.repolens.api;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.InputStream;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.Semaphore;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Local same-origin binary/SSE adapter. Deployment ingress may route these directly. */
@RestController
public class AgentFilesProxyController {
    @org.springframework.beans.factory.annotation.Value("${app.agent-url:http://127.0.0.1:8092}") private String backend;
    private final HttpClient client=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(2)).build();
    private final Semaphore streams=new Semaphore(4);
    @RequestMapping(value={"/agent/uploads","/agent/uploads/{upload}","/agent/uploads/{upload}/parts/{part}","/agent/uploads/{upload}/complete","/agent/uploads/{upload}/download","/agent/uploads/{upload}/content","/agent/memory"},method={RequestMethod.GET,RequestMethod.POST,RequestMethod.PUT})
    public ResponseEntity<byte[]> file(HttpServletRequest incoming) throws Exception {
        String path=incoming.getRequestURI().substring("/agent".length());
        if(!path.matches("/uploads(/[a-f0-9]{32}(/parts/[1-3]|/complete|/download|/content)?)?|/memory"))return ResponseEntity.badRequest().build();
        byte[] body=incoming.getInputStream().readNBytes(5*1024*1024+1);
        if(body.length>5*1024*1024)return ResponseEntity.status(413).build();
        var request=HttpRequest.newBuilder(URI.create(backend+path)).timeout(Duration.ofSeconds(30))
            .header("Authorization",incoming.getHeader("Authorization"))
            .header("Content-Type",path.contains("/parts/")?"application/octet-stream":"application/json");
        cn.hm.repolens.domain.TraceContext.inject(request);
        if(path.contains("/parts/")){
            String digest=incoming.getHeader("X-Content-Sha256");
            if(digest==null||!digest.matches("[a-f0-9]{64}"))return ResponseEntity.badRequest().build();
            request.header("X-Content-Sha256",digest);
        }
        request.method(incoming.getMethod(),body.length==0?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofByteArray(body));
        try {
            var response=client.send(request.build(),HttpResponse.BodyHandlers.ofInputStream());
            try(var input=response.body()) {
                int maxResponse=path.endsWith("/content")?16_001_000:12_000_000;
                byte[] bytes=input.readNBytes(maxResponse+1);
                if(bytes.length>maxResponse)return ResponseEntity.status(502).build();
                var result=ResponseEntity.status(response.statusCode()).header("Content-Type",response.headers().firstValue("Content-Type").orElse("application/json"));
                response.headers().firstValue("Content-Disposition").ifPresent(v->result.header("Content-Disposition",v));
                return result.body(bytes);
            }
        } catch(java.io.IOException e){return ResponseEntity.status(503).header("Content-Type","application/json").body("{\"message\":\"资料服务暂不可用，请稍后重试\"}".getBytes(StandardCharsets.UTF_8));}
    }
    @GetMapping("/agent/jobs/{id}/stream")
    public void stream(@PathVariable String id,HttpServletRequest incoming,HttpServletResponse output) throws Exception {
        if(!id.matches("[a-fA-F0-9-]{36}")){output.setStatus(400);return;}
        if(!streams.tryAcquire()){output.setStatus(429);return;}
        try {
            String after=incoming.getParameter("after");
            if(after!=null&&!after.matches("[0-9]{1,15}")){output.setStatus(400);return;}
            var request=HttpRequest.newBuilder(URI.create(backend+"/jobs/"+id+"/stream"+(after==null?"":"?after="+after)))
                .timeout(Duration.ofSeconds(10)).header("Authorization",incoming.getHeader("Authorization"));
            cn.hm.repolens.domain.TraceContext.inject(request);
            String last=incoming.getHeader("Last-Event-ID");
            if(last!=null&&last.matches("[0-9]{1,15}"))request.header("Last-Event-ID",last);
            var response=client.send(request.GET().build(),HttpResponse.BodyHandlers.ofInputStream());
            output.setStatus(response.statusCode());
            output.setContentType(response.headers().firstValue("Content-Type").orElse("application/json"));
            output.setHeader("Cache-Control","no-cache");output.setHeader("X-Accel-Buffering","no");
            try(InputStream input=response.body()) {
                byte[] buffer=new byte[4096];int count;
                while((count=input.read(buffer))!=-1){output.getOutputStream().write(buffer,0,count);output.flushBuffer();}
            }
        } finally {streams.release();}
    }
}
