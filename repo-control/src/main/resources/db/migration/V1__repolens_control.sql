CREATE TABLE app_user (
  id VARCHAR(80) PRIMARY KEY, password_hash VARCHAR(100) NOT NULL,
  role VARCHAR(20) NOT NULL
);
CREATE TABLE outbox_event (
  id VARCHAR(36) PRIMARY KEY, topic VARCHAR(60) NOT NULL, aggregate_id VARCHAR(36) NOT NULL,
  payload VARCHAR(4000) NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
  attempts INT NOT NULL DEFAULT 0, available_at TIMESTAMP(6) NOT NULL,
  created_at TIMESTAMP(6) NOT NULL, last_error VARCHAR(300),
  lease_until TIMESTAMP(6), lease_token VARCHAR(36)
);
CREATE INDEX ix_outbox_dispatch ON outbox_event(status, available_at);
CREATE TABLE consumer_receipt (
  consumer_name VARCHAR(60) NOT NULL, event_id VARCHAR(36) NOT NULL,
  created_at TIMESTAMP(6) NOT NULL, PRIMARY KEY (consumer_name, event_id)
);
CREATE TABLE agent_workspace (
  id VARCHAR(36) PRIMARY KEY, owner_id VARCHAR(80) NOT NULL,
  name VARCHAR(120) NOT NULL, created_at TIMESTAMP(6) NOT NULL
);
CREATE TABLE agent_job (
  id VARCHAR(36) PRIMARY KEY, workspace_id VARCHAR(36) NOT NULL,
  owner_id VARCHAR(80) NOT NULL, idem_key VARCHAR(100) NOT NULL,
  repo_url VARCHAR(300) NOT NULL, commit_sha VARCHAR(40) NOT NULL,
  question VARCHAR(4000) NOT NULL, status VARCHAR(20) NOT NULL,
  attempt BIGINT NOT NULL DEFAULT 0, lease_token VARCHAR(36), lease_until TIMESTAMP(6),
  result_ref VARCHAR(500), error_code VARCHAR(80), created_at TIMESTAMP(6) NOT NULL,
  UNIQUE(owner_id,idem_key), FOREIGN KEY(workspace_id) REFERENCES agent_workspace(id)
);
CREATE INDEX ix_agent_recovery ON agent_job(status,lease_until);
CREATE TABLE agent_approval (
  id VARCHAR(36) PRIMARY KEY, job_id VARCHAR(36) NOT NULL,
  plan_hash VARCHAR(64) NOT NULL, status VARCHAR(20) NOT NULL,
  expires_at TIMESTAMP(6) NOT NULL, approved_by VARCHAR(80),
  UNIQUE(job_id,plan_hash), FOREIGN KEY(job_id) REFERENCES agent_job(id)
);

CREATE TABLE agent_followup (
  job_id VARCHAR(36) PRIMARY KEY, parent_job_id VARCHAR(36) NOT NULL,
  FOREIGN KEY(job_id) REFERENCES agent_job(id),
  FOREIGN KEY(parent_job_id) REFERENCES agent_job(id)
);

CREATE TABLE consumer_failure (
  consumer_name VARCHAR(80) NOT NULL,event_id VARCHAR(100) NOT NULL,
  observations INT NOT NULL,last_reconsume INT NOT NULL,error_class VARCHAR(160) NOT NULL,
  status VARCHAR(20) NOT NULL,updated_at TIMESTAMP(6) NOT NULL,
  PRIMARY KEY(consumer_name,event_id)
);

ALTER TABLE outbox_event ADD COLUMN trace_parent VARCHAR(55);
CREATE TABLE agent_trace(job_id VARCHAR(36) PRIMARY KEY,trace_parent VARCHAR(55));

ALTER TABLE agent_job ADD COLUMN generation BIGINT NOT NULL DEFAULT 0;
ALTER TABLE agent_job ADD COLUMN approval_hash VARCHAR(64);

