package cn.hm.repolens.api;

import cn.hm.repolens.domain.*;
import cn.hm.repolens.domain.AgentRows.*;
import cn.hm.repolens.persistence.AgentMapper;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
public class AgentControlController {
  private final AgentJobService service;
  private final AgentMapper db;
  private final ControlClock time;
  private final String secret;

  public AgentControlController(
      AgentJobService service,
      AgentMapper db,
      ControlClock time,
      @Value("${AGENT_INTERNAL_SECRET:}") String secret) {
    this.service = service;
    this.db = db;
    this.time = time;
    this.secret = secret;
  }

  public record WorkspaceInput(@NotBlank @Size(max = 120) String name) {}

  public record JobInput(
      @NotBlank String workspaceId,
      @NotBlank @Size(max = 100) String idempotencyKey,
      @NotBlank @Size(max = 300) String repoUrl,
      @NotBlank String commitSha,
      @NotBlank @Size(max = 4000) String question) {}

  public record Lease(@NotBlank String token) {}

  public record Completion(
      @NotBlank String token,
      @NotBlank String status,
      @Size(max = 500) String resultRef,
      @Size(max = 80) String errorCode,
      @Pattern(regexp = "[a-f0-9]{64}") String approvalHash) {}

  public record ApprovalResume(@NotBlank @Pattern(regexp = "[a-f0-9]{64}") String planHash) {}

  public record Followup(
      @NotBlank @Size(max = 100) String idempotencyKey,
      @NotBlank @Size(max = 4000) String question) {}

  @GetMapping("/api/me")
  public Object me(Authentication a) {
    return Map.of(
        "id", a.getName(), "roles", a.getAuthorities().stream().map(Object::toString).toList());
  }

  @GetMapping("/api/agent/workspaces")
  public Object workspaces(Authentication a) {
    return db.workspaces(a.getName());
  }

  @PostMapping("/api/agent/workspaces")
  public Workspace workspace(Authentication a, @Valid @RequestBody WorkspaceInput b) {
    return service.workspace(a.getName(), b.name());
  }

  @PostMapping("/api/agent/jobs")
  public Job create(Authentication a, @Valid @RequestBody JobInput b) {
    return service.create(
        a.getName(), b.workspaceId(), b.idempotencyKey(), b.repoUrl(), b.commitSha(), b.question());
  }

  @GetMapping("/api/agent/jobs")
  public Object jobs(Authentication a) {
    return db.jobs(a.getName());
  }

  @GetMapping("/api/agent/jobs/{id}")
  public Job job(Authentication a, @PathVariable String id) {
    return service.ownJob(a.getName(), id);
  }

  @PostMapping("/api/agent/jobs/{id}/cancel")
  public Job cancel(Authentication a, @PathVariable String id) {
    return service.cancel(a.getName(), id);
  }

  @PostMapping("/api/agent/jobs/{id}/resume")
  public Job resume(
      Authentication a, @PathVariable String id, @Valid @RequestBody ApprovalResume body) {
    return service.resume(a.getName(), id, body.planHash());
  }

  @PostMapping("/api/agent/jobs/{id}/retry")
  public Job retry(Authentication a, @PathVariable String id) {
    return service.retry(a.getName(), id);
  }

  @PostMapping("/api/agent/jobs/{id}/followup")
  public Job followup(Authentication a, @PathVariable String id, @Valid @RequestBody Followup b) {
    return service.followup(a.getName(), id, b.idempotencyKey(), b.question());
  }

  private void internal(String key) {
    if (secret.length() < 32
        || key == null
        || !MessageDigest.isEqual(
            secret.getBytes(StandardCharsets.UTF_8), key.getBytes(StandardCharsets.UTF_8)))
      throw new DomainException(401, "INTERNAL_AUTH", "内部凭证无效");
  }

  @GetMapping("/internal/agent-jobs")
  public Object recover(@RequestHeader("X-Service-Key") String key) {
    internal(key);
    return db.recoverable(time.now());
  }

  @GetMapping("/internal/agent-jobs/{id}")
  public Job internalJob(@RequestHeader("X-Service-Key") String key, @PathVariable String id) {
    internal(key);
    Job j = db.job(id);
    if (j == null) throw DomainException.missing();
    return j;
  }

  @GetMapping("/internal/agent-jobs/{id}/parent")
  public Object parent(@RequestHeader("X-Service-Key") String key, @PathVariable String id) {
    internal(key);
    return Map.of("parentJobId", java.util.Objects.requireNonNullElse(db.parent(id), ""));
  }

  @GetMapping("/internal/agent-jobs/{id}/trace")
  public Object trace(@RequestHeader("X-Service-Key") String key, @PathVariable String id) {
    internal(key);
    return Map.of("traceParent", java.util.Objects.requireNonNullElse(db.traceParent(id), ""));
  }

  @PostMapping("/internal/agent-jobs/{id}/claim")
  public Job claim(@RequestHeader("X-Service-Key") String key, @PathVariable String id) {
    internal(key);
    return service.claim(id);
  }

  @PostMapping("/internal/agent-jobs/{id}/heartbeat")
  public Job heartbeat(
      @RequestHeader("X-Service-Key") String key,
      @PathVariable String id,
      @Valid @RequestBody Lease b) {
    internal(key);
    return service.heartbeat(id, b.token());
  }

  @PostMapping("/internal/agent-jobs/{id}/finish")
  public Job finish(
      @RequestHeader("X-Service-Key") String key,
      @PathVariable String id,
      @Valid @RequestBody Completion b) {
    internal(key);
    return service.finish(
        id, b.token(), b.status(), b.resultRef(), b.errorCode(), b.approvalHash());
  }

  @PostMapping("/internal/agent-jobs/{id}/resume")
  public Job resumeInternal(
      @RequestHeader("X-Service-Key") String key,
      @PathVariable String id,
      @Valid @RequestBody ApprovalResume body) {
    internal(key);
    return service.resume(null, id, body.planHash());
  }

  @PostMapping("/internal/agent-jobs/{id}/bind-approval")
  public Job bindApproval(
      @RequestHeader("X-Service-Key") String key,
      @PathVariable String id,
      @Valid @RequestBody ApprovalResume body) {
    internal(key);
    return service.bindApproval(id, body.planHash());
  }
}
