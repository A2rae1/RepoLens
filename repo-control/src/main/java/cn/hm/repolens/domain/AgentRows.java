package cn.hm.repolens.domain;

import java.time.LocalDateTime;

public final class AgentRows {
  private AgentRows() {}

  public record Workspace(String id, String ownerId, String name, LocalDateTime createdAt) {}

  public record Job(
      String id,
      String workspaceId,
      String ownerId,
      String idemKey,
      String repoUrl,
      String commitSha,
      String question,
      String status,
      long attempt,
      String leaseToken,
      LocalDateTime leaseUntil,
      String resultRef,
      String errorCode,
      LocalDateTime createdAt,
      long generation,
      String approvalHash) {}
}
