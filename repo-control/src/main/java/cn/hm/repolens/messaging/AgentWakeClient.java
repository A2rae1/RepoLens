package cn.hm.repolens.messaging;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
@Component
public class AgentWakeClient {
    private final HttpClient client=HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).connectTimeout(Duration.ofSeconds(2)).build();
    @Value("${AGENT_INTERNAL_SECRET:}")private String secret;
    @Value("${app.agent-url:http://127.0.0.1:8092}")private String backend;
    public void wake(String job) throws Exception {signal(job,"wake");}
    public void cancel(String job) throws Exception {signal(job,"cancel");}
    private void signal(String job,String action) throws Exception {
        if(secret.length()<32)throw new IllegalStateException("Internal service key not configured");
        if(!job.matches("[a-fA-F0-9-]{36}"))throw new IllegalArgumentException("Invalid job id");
        var request=HttpRequest.newBuilder(URI.create(backend+"/internal/jobs/"+job+"/"+action)).timeout(Duration.ofSeconds(3)).header("X-Service-Key",secret).POST(HttpRequest.BodyPublishers.ofString("{}")).build();
        var traced=HttpRequest.newBuilder(request,(name,value)->true);cn.hm.repolens.domain.TraceContext.inject(traced);
        if(client.send(traced.build(),HttpResponse.BodyHandlers.discarding()).statusCode()!=200)throw new IllegalStateException("Agent did not accept task wakeup");
    }
}
