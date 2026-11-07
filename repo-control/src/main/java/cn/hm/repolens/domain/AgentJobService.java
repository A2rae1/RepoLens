package cn.hm.repolens.domain;

import cn.hm.repolens.domain.AgentRows.*;
import cn.hm.repolens.persistence.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AgentJobService {
  private final AgentMapper db;
  private final ControlMapper events;
  private final ControlClock time;

  public AgentJobService(AgentMapper db, ControlMapper events, ControlClock time) {
    this.db = db;
    this.events = events;
    this.time = time;
  }

  public Workspace ownWorkspace(String owner, String id) {
    Workspace w = db.workspace(id);
    if (w == null) throw DomainException.missing();
    if (!w.ownerId().equals(owner)) throw DomainException.forbidden();
    return w;
  }

  public Job ownJob(String owner, String id) {
    Job j = db.job(id);
    if (j == null) throw DomainException.missing();
    if (!j.ownerId().equals(owner)) throw DomainException.forbidden();
    return j;
  }

  @Transactional
  public Workspace workspace(String owner, String name) {
    Workspace w = new Workspace(ControlClock.id(), owner, name, time.now());
    db.insertWorkspace(w);
    return w;
  }

  @Transactional
  public Job create(
      String owner, String workspace, String key, String repo, String commit, String question) {
    ownWorkspace(owner, workspace);
    if (repo == null
        || commit == null
        || !repo.matches("https://github\\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
        || !commit.matches("[a-fA-F0-9]{40}")
        || Arrays.stream(repo.substring("https://github.com/".length()).split("/"))
            .anyMatch(part -> part.equals(".") || part.equals("..")))
      throw new DomainException(400, "INVALID_REPO", "仅支持公开GitHub仓库根地址和完整40位commit");
    commit = commit.toLowerCase(Locale.ROOT);
    Job old = db.byKey(owner, key);
    if (old != null) {
      if (!old.workspaceId().equals(workspace)
          || !old.repoUrl().equals(repo)
          || !old.commitSha().equals(commit)
          || !old.question().equals(question)) throw DomainException.conflict("幂等键已绑定不同任务内容");
      return old;
    }
    Job j =
        new Job(
            ControlClock.id(),
            workspace,
            owner,
            key,
            repo,
            commit.toLowerCase(),
            question,
            "QUEUED",
            0,
            null,
            null,
            null,
            null,
            time.now(),
            0,
            null);
    db.insertJob(j);
    db.trace(j.id(), TraceContext.parent());
    events.outbox(ControlClock.id(), "AGENT_JOB_CREATED", j.id(), j.id(), time.now());
    return db.job(j.id());
  }

  @Transactional
  public Job claim(String id) {
    String token = ControlClock.id();
    if (db.claim(id, token, time.now(), time.now().plusSeconds(90)) != 1)
      throw DomainException.conflict("任务已被领取或结束");
    return db.job(id);
  }

  @Transactional
  public Job heartbeat(String id, String token) {
    if (db.heartbeat(id, token, time.now(), time.now().plusSeconds(90)) != 1)
      throw DomainException.conflict("执行租约已失效");
    return db.job(id);
  }

  @Transactional
  public Job finish(String id, String token, String status, String result, String error) {
    return finish(id, token, status, result, error, null);
  }

  @Transactional
  public Job finish(
      String id, String token, String status, String result, String error, String approval) {
    if (!Set.of("COMPLETED", "FAILED", "AWAITING_APPROVAL").contains(status))
      throw DomainException.conflict("不允许的任务结束状态");
    if (status.equals("AWAITING_APPROVAL")
        && (approval == null || !approval.matches("[a-f0-9]{64}")))
      throw DomainException.conflict("等待审批必须绑定计划哈希");
    if (db.finish(id, token, status, result, error, approval, time.now()) != 1)
      throw DomainException.conflict("陈旧执行结果被拒绝");
    return db.job(id);
  }

  @Transactional
  public Job cancel(String owner, String id) {
    ownJob(owner, id);
    if (db.cancel(id) > 0)
      events.outbox(ControlClock.id(), "AGENT_JOB_CANCELLED", id, id, time.now());
    return db.job(id);
  }

  @Transactional
  public Job resume(String owner, String id, String hash) {
    Job job = db.lockJob(id);
    if (job == null) throw DomainException.missing();
    if (owner != null && !job.ownerId().equals(owner)) throw DomainException.forbidden();
    if (hash == null || !hash.matches("[a-f0-9]{64}"))
      throw DomainException.conflict("需要有效的审批计划哈希");
    if (job.status().equals("AWAITING_APPROVAL")) {
      if (db.resume(id, hash) != 1) throw DomainException.conflict("审批计划已经改变");
      events.outbox(ControlClock.id(), "AGENT_JOB_CREATED", id, id, time.now());
      return db.job(id);
    }
    // The same durable decision may be replayed after a lost HTTP response.
    if (hash.equals(job.approvalHash())
        && Set.of("QUEUED", "RUNNING", "COMPLETED", "FAILED").contains(job.status())) return job;
    throw DomainException.conflict("任务未等待此审批或已经取消");
  }

  /** Upgrade a legacy waiting job from its trusted Python checkpoint without queueing it. */
  @Transactional
  public Job bindApproval(String id, String hash) {
    Job job = db.lockJob(id);
    if (job == null) throw DomainException.missing();
    if (hash == null || !hash.matches("[a-f0-9]{64}") || !job.status().equals("AWAITING_APPROVAL"))
      throw DomainException.conflict("任务未等待审批");
    if (job.approvalHash() == null) db.bindApproval(id, hash);
    else if (!hash.equals(job.approvalHash())) throw DomainException.conflict("审批计划已经改变");
    return db.job(id);
  }

  @Transactional
  public Job retry(String owner, String id) {
    ownJob(owner, id);
    if (db.retry(id) != 1) throw DomainException.conflict("仅失败任务允许显式重试");
    events.outbox(ControlClock.id(), "AGENT_JOB_CREATED", id, id, time.now());
    return db.job(id);
  }

  @Transactional
  public Job followup(String owner, String parentId, String key, String question) {
    Job parent = ownJob(owner, parentId);
    if (!parent.status().equals("COMPLETED")) throw DomainException.conflict("前一轮调研尚未完成");
    Job child =
        create(owner, parent.workspaceId(), key, parent.repoUrl(), parent.commitSha(), question);
    String linked = db.parent(child.id());
    if (linked == null) db.followup(child.id(), parentId);
    else if (!linked.equals(parentId)) throw DomainException.conflict("幂等键已关联其他对话");
    return child;
  }
}
