package cn.hm.repolens;

import static org.assertj.core.api.Assertions.*;

import cn.hm.repolens.domain.*;
import cn.hm.repolens.domain.AgentRows.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

@SpringBootTest
@ActiveProfiles("test")
class AgentControlTest {
  @Autowired AgentJobService jobs;
  @Autowired org.springframework.jdbc.core.JdbcTemplate jdbc;

  @Test
  void commitNormalizationDoesNotBreakIdempotentReplay() {
    Workspace w = jobs.workspace("alice", "canonical-sha");
    String key = java.util.UUID.randomUUID().toString();
    Job first =
        jobs.create(
            "alice", w.id(), key, "https://github.com/pallets/click", "B".repeat(40), "same task");
    assertThat(
            jobs.create(
                    "alice",
                    w.id(),
                    key,
                    "https://github.com/pallets/click",
                    "B".repeat(40),
                    "same task")
                .id())
        .isEqualTo(first.id());
    assertThatThrownBy(
            () ->
                jobs.create(
                    "alice",
                    w.id(),
                    "invalid",
                    "https://github.com/../click",
                    "b".repeat(40),
                    "bad path"))
        .isInstanceOf(DomainException.class);
  }

  @Test
  void dedupeClaimCancelAndStaleResultAreEnforced() {
    Workspace w = jobs.workspace("alice", "测试");
    String sha = "a".repeat(40);
    Job j = jobs.create("alice", w.id(), w.id(), "https://github.com/pallets/flask", sha, "版本要求");
    assertThat(
            jobs.create("alice", w.id(), w.id(), "https://github.com/pallets/flask", sha, "版本要求")
                .id())
        .isEqualTo(j.id());
    assertThatThrownBy(
            () -> jobs.create("bob", w.id(), "x", "https://github.com/pallets/flask", sha, "x"))
        .isInstanceOf(DomainException.class);
    Job claimed = jobs.claim(j.id());
    assertThat(claimed.attempt()).isEqualTo(1);
    assertThatThrownBy(() -> jobs.claim(j.id())).isInstanceOf(DomainException.class);
    jobs.cancel("alice", j.id());
    assertThatThrownBy(() -> jobs.finish(j.id(), claimed.leaseToken(), "COMPLETED", "report", null))
        .isInstanceOf(DomainException.class);
  }

  @Test
  void expiredAttemptIsFencedWhenNewWorkerClaims() {
    Workspace w = jobs.workspace("alice", "lease-test");
    Job j =
        jobs.create(
            "alice", w.id(), w.id(), "https://github.com/pallets/click", "b".repeat(40), "test");
    Job old = jobs.claim(j.id());
    jdbc.update(
        "UPDATE agent_job SET lease_until=? WHERE id=?",
        java.time.LocalDateTime.now(java.time.ZoneOffset.UTC).minusMinutes(1),
        j.id());
    Job next = jobs.claim(j.id());
    assertThat(next.attempt()).isEqualTo(old.attempt() + 1);
    assertThatThrownBy(() -> jobs.finish(j.id(), old.leaseToken(), "COMPLETED", "stale", null))
        .isInstanceOf(DomainException.class);
    assertThat(jobs.finish(j.id(), next.leaseToken(), "COMPLETED", "valid", null).resultRef())
        .isEqualTo("valid");
  }

  @Test
  void approvalResumeIsBoundAndIdempotentAfterALostResponse() {
    Workspace w = jobs.workspace("alice", "approval-replay");
    Job j =
        jobs.create(
            "alice", w.id(), w.id(), "https://github.com/pallets/click", "b".repeat(40), "test");
    Job claim = jobs.claim(j.id());
    String hash = "a".repeat(64);
    jobs.finish(j.id(), claim.leaseToken(), "AWAITING_APPROVAL", null, null, hash);
    assertThatThrownBy(() -> jobs.resume("alice", j.id(), "b".repeat(64)))
        .isInstanceOf(DomainException.class);
    assertThatThrownBy(() -> jobs.resume("bob", j.id(), hash)).isInstanceOf(DomainException.class);
    jobs.resume("alice", j.id(), hash);
    jobs.resume("alice", j.id(), hash);
    Job running = jobs.claim(j.id());
    jobs.resume(null, j.id(), hash);
    jobs.finish(j.id(), running.leaseToken(), "COMPLETED", "report", null);
    assertThat(jobs.resume(null, j.id(), hash).status()).isEqualTo("COMPLETED");
    assertThat(
            jdbc.queryForObject(
                "SELECT COUNT(*) FROM outbox_event WHERE topic='AGENT_JOB_CREATED' AND"
                    + " aggregate_id=?",
                Integer.class,
                j.id()))
        .isEqualTo(2);
  }

  @Test
  void explicitRetryChangesGenerationButLeaseRecoveryDoesNot() {
    Workspace w = jobs.workspace("alice", "retry-generation");
    Job j =
        jobs.create(
            "alice", w.id(), w.id(), "https://github.com/pallets/click", "b".repeat(40), "test");
    Job first = jobs.claim(j.id());
    jdbc.update(
        "UPDATE agent_job SET lease_until=? WHERE id=?",
        java.time.LocalDateTime.now(java.time.ZoneOffset.UTC).minusMinutes(1),
        j.id());
    Job recovered = jobs.claim(j.id());
    assertThat(recovered.generation()).isZero();
    assertThat(recovered.attempt()).isEqualTo(first.attempt() + 1);
    jobs.finish(j.id(), recovered.leaseToken(), "FAILED", null, "STEP_LIMIT");
    Job retried = jobs.retry("alice", j.id());
    assertThat(retried.generation()).isEqualTo(1);
    assertThat(retried.approvalHash()).isNull();
    assertThat(retried.resultRef()).isNull();
    assertThatThrownBy(() -> jobs.finish(j.id(), first.leaseToken(), "COMPLETED", "stale", null))
        .isInstanceOf(DomainException.class);
  }
}
