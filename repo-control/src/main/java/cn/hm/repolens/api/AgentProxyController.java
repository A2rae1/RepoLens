package cn.hm.repolens.api;

import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Same-origin UI adapter with a fixed loopback target, no arbitrary URL forwarding. */
@RestController
public class AgentProxyController {
  @org.springframework.beans.factory.annotation.Value("${app.agent-url:http://127.0.0.1:8092}")
  private String backend;

  private final HttpClient client =
      HttpClient.newBuilder()
          .version(HttpClient.Version.HTTP_1_1)
          .connectTimeout(Duration.ofSeconds(2))
          .build();

  @RequestMapping(
      value = {
        "/agent/jobs/{id}/events",
        "/agent/jobs/{id}/report",
        "/agent/jobs/{id}/approval",
        "/agent/jobs/{id}/approval/renew",
        "/agent/jobs/{id}/start",
        "/agent/jobs/{id}/export",
        "/agent/jobs/{id}/artifacts/{artifact}"
      },
      method = {RequestMethod.GET, RequestMethod.POST})
  public ResponseEntity<byte[]> proxy(
      @PathVariable String id,
      HttpServletRequest incoming,
      @RequestBody(required = false) byte[] body)
      throws Exception {
    if (!id.matches("[a-fA-F0-9-]{36}") || (body != null && body.length > 4096))
      return ResponseEntity.badRequest().build();
    String path = incoming.getRequestURI().substring("/agent".length());
    if (!path.matches(
        "/jobs/[a-fA-F0-9-]{36}/(events|report|approval(/renew)?|start|export|artifacts/[a-f0-9]{64})"))
      return ResponseEntity.badRequest().build();
    String after = incoming.getParameter("after");
    if (after != null) {
      if (!after.matches("[0-9]{1,15}")) return ResponseEntity.badRequest().build();
      path += "?after=" + after;
    }
    URI target = URI.create(backend + path);
    HttpRequest.Builder request =
        HttpRequest.newBuilder(target)
            .timeout(Duration.ofSeconds(12))
            .header("Authorization", incoming.getHeader("Authorization"))
            .header("Content-Type", "application/json");
    cn.hm.repolens.domain.TraceContext.inject(request);
    if (incoming.getMethod().equals("POST"))
      request.POST(HttpRequest.BodyPublishers.ofByteArray(body == null ? new byte[0] : body));
    else request.GET();
    try {
      HttpResponse<byte[]> response =
          client.send(request.build(), HttpResponse.BodyHandlers.ofByteArray());
      var result =
          ResponseEntity.status(response.statusCode())
              .header(
                  "Content-Type",
                  response.headers().firstValue("Content-Type").orElse("application/json"));
      response
          .headers()
          .firstValue("Content-Disposition")
          .ifPresent(v -> result.header("Content-Disposition", v));
      return result.body(response.body());
    } catch (java.io.IOException e) {
      return ResponseEntity.status(503)
          .header("Content-Type", "application/json")
          .body("{\"message\":\"调研服务暂未启动\"}".getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }
  }
}
