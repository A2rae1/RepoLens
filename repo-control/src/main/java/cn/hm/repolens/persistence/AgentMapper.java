package cn.hm.repolens.persistence;

import cn.hm.repolens.domain.AgentRows.*;
import java.time.LocalDateTime;
import java.util.List;
import org.apache.ibatis.annotations.*;

public interface AgentMapper {
  @Insert("INSERT INTO agent_trace VALUES(#{id},#{parent})")
  int trace(@Param("id") String id, @Param("parent") String parent);

  @Select("SELECT trace_parent FROM agent_trace WHERE job_id=#{id}")
  String traceParent(String id);

  @Insert("INSERT INTO agent_workspace VALUES(#{id},#{ownerId},#{name},#{createdAt})")
  int insertWorkspace(Workspace w);

  @Select("SELECT * FROM agent_workspace WHERE id=#{id}")
  Workspace workspace(String id);

  @Select(
      "SELECT * FROM agent_workspace WHERE owner_id=#{owner} ORDER BY created_at DESC LIMIT 100")
  List<Workspace> workspaces(String owner);

  @Insert(
      "INSERT INTO"
          + " agent_job(id,workspace_id,owner_id,idem_key,repo_url,commit_sha,question,status,attempt,created_at)"
          + " VALUES(#{id},#{workspaceId},#{ownerId},#{idemKey},#{repoUrl},#{commitSha},#{question},'QUEUED',0,#{createdAt})")
  int insertJob(Job j);

  @Select("SELECT * FROM agent_job WHERE id=#{id}")
  Job job(String id);

  @Select("SELECT * FROM agent_job WHERE id=#{id} FOR UPDATE")
  Job lockJob(String id);

  @Select("SELECT * FROM agent_job WHERE owner_id=#{owner} AND idem_key=#{key}")
  Job byKey(@Param("owner") String owner, @Param("key") String key);

  @Select("SELECT * FROM agent_job WHERE owner_id=#{owner} ORDER BY created_at DESC LIMIT 100")
  List<Job> jobs(String owner);

  @Select(
      "SELECT * FROM agent_job WHERE status='QUEUED' OR (status='RUNNING' AND lease_until<=#{now})"
          + " ORDER BY created_at LIMIT 50")
  List<Job> recoverable(LocalDateTime now);

  @Update(
      "UPDATE agent_job SET"
          + " status='RUNNING',attempt=attempt+1,lease_token=#{token},lease_until=#{until} WHERE"
          + " id=#{id} AND (status='QUEUED' OR (status='RUNNING' AND lease_until<=#{now}))")
  int claim(
      @Param("id") String id,
      @Param("token") String token,
      @Param("now") LocalDateTime now,
      @Param("until") LocalDateTime until);

  @Update(
      "UPDATE agent_job SET lease_until=#{until} WHERE id=#{id} AND status='RUNNING' AND"
          + " lease_token=#{token} AND lease_until>#{now}")
  int heartbeat(
      @Param("id") String id,
      @Param("token") String token,
      @Param("now") LocalDateTime now,
      @Param("until") LocalDateTime until);

  @Update(
      "UPDATE agent_job SET"
          + " status=#{status},result_ref=#{result},error_code=#{error},approval_hash=COALESCE(#{approval},approval_hash),lease_until=NULL"
          + " WHERE id=#{id} AND status='RUNNING' AND lease_token=#{token} AND lease_until>#{now}")
  int finish(
      @Param("id") String id,
      @Param("token") String token,
      @Param("status") String status,
      @Param("result") String result,
      @Param("error") String error,
      @Param("approval") String approval,
      @Param("now") LocalDateTime now);

  @Update(
      "UPDATE agent_job SET status='CANCELLED',lease_token=NULL,lease_until=NULL WHERE id=#{id} AND"
          + " status IN ('QUEUED','RUNNING','AWAITING_APPROVAL')")
  int cancel(String id);

  @Update(
      "UPDATE agent_job SET status='QUEUED',approval_hash=#{hash} WHERE id=#{id} AND"
          + " status='AWAITING_APPROVAL' AND (approval_hash=#{hash} OR approval_hash IS NULL)")
  int resume(@Param("id") String id, @Param("hash") String hash);

  @Update(
      "UPDATE agent_job SET approval_hash=#{hash} WHERE id=#{id} AND status='AWAITING_APPROVAL' AND"
          + " approval_hash IS NULL")
  int bindApproval(@Param("id") String id, @Param("hash") String hash);

  @Update(
      "UPDATE agent_job SET"
          + " status='QUEUED',generation=generation+1,approval_hash=NULL,result_ref=NULL,error_code=NULL,lease_token=NULL,lease_until=NULL"
          + " WHERE id=#{id} AND status='FAILED'")
  int retry(String id);

  @Insert("INSERT INTO agent_followup VALUES(#{child},#{parent})")
  int followup(@Param("child") String child, @Param("parent") String parent);

  @Select("SELECT parent_job_id FROM agent_followup WHERE job_id=#{id}")
  String parent(String id);
}
