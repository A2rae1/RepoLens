"""Application artifacts and cost ledger. LangGraph checkpoints use a separate official saver."""

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .pricing import cny_upper


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "artifacts.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, workspace TEXT NOT NULL,
                    repo TEXT NOT NULL, commit_sha TEXT NOT NULL, created REAL NOT NULL,
                    UNIQUE(owner,workspace,repo,commit_sha)
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,snapshot TEXT NOT NULL,path TEXT NOT NULL,
                    start_line INTEGER NOT NULL,end_line INTEGER NOT NULL,content TEXT NOT NULL,
                    digest TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_chunks_snapshot ON chunks(snapshot);
                CREATE TABLE IF NOT EXISTS source_files (
                    snapshot TEXT NOT NULL,path TEXT NOT NULL,content TEXT NOT NULL,
                    digest TEXT NOT NULL,PRIMARY KEY(snapshot,path)
                );
                CREATE TABLE IF NOT EXISTS symbols(
                    snapshot TEXT NOT NULL,path TEXT NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,
                    start_line INTEGER NOT NULL,end_line INTEGER NOT NULL,
                    PRIMARY KEY(snapshot,path,name,start_line)
                );
                CREATE INDEX IF NOT EXISTS ix_symbol_name ON symbols(snapshot,name);
                CREATE TABLE IF NOT EXISTS symbol_index_versions(snapshot TEXT PRIMARY KEY,version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshot_archives(snapshot TEXT PRIMARY KEY,digest TEXT NOT NULL,path TEXT NOT NULL,tree_digest TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS evidence_fts USING fts5(
                    chunk_id UNINDEXED,snapshot UNINDEXED,path,content,tokenize='unicode61'
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,job TEXT NOT NULL,kind TEXT NOT NULL,
                    data TEXT NOT NULL,created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_events_job ON events(job,seq);
                CREATE TABLE IF NOT EXISTS reports(job TEXT PRIMARY KEY,owner TEXT NOT NULL,body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS preferences (
                    owner TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,
                    PRIMARY KEY(owner,key)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    job TEXT NOT NULL,plan_hash TEXT NOT NULL,plan TEXT NOT NULL,
                    expires REAL NOT NULL,decision TEXT,claimed INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(job,plan_hash)
                );
                CREATE TABLE IF NOT EXISTS executions (
                    job TEXT NOT NULL,plan_hash TEXT NOT NULL,status TEXT NOT NULL,
                    result TEXT,PRIMARY KEY(job,plan_hash)
                );
                CREATE TABLE IF NOT EXISTS model_calls (
                    id TEXT PRIMARY KEY,job TEXT NOT NULL,reserved_cny REAL NOT NULL,
                    status TEXT NOT NULL,input_tokens INTEGER,output_tokens INTEGER,
                    cached_tokens INTEGER,latency_ms REAL,model TEXT NOT NULL,created REAL NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, job: str, kind: str, data: dict) -> int:
        with self.connect() as db:
            cur = db.execute(
                "INSERT INTO events(job,kind,data,created) VALUES(?,?,?,?)",
                (job, kind, json.dumps(data, ensure_ascii=False), time.time()),
            )
            return cur.lastrowid

    def events(self, job: str, after: int = 0) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM events WHERE job=? AND seq>? ORDER BY seq LIMIT 100", (job, after)
            ).fetchall()
            return [dict(row) | {"data": json.loads(row["data"])} for row in rows]

    def snapshot(self, snapshot_id: str, owner: str, workspace: str | None = None) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM snapshots WHERE id=? AND owner=?", (snapshot_id, owner)
            ).fetchone()
        if not row or (workspace is not None and row["workspace"] != workspace):
            raise PermissionError("Snapshot is absent or outside this workspace")
        return dict(row)

    def report(self, job: str, owner: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT body FROM reports WHERE job=? AND owner=?", (job, owner)).fetchone()
        return json.loads(row["body"]) if row else None

    def save_report(self, job: str, owner: str, body: dict) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO reports VALUES(?,?,?) ON CONFLICT(job) DO UPDATE SET body=excluded.body",
                (job, owner, json.dumps(body, ensure_ascii=False)),
            )

    def reserve_call(self, job: str, model: str, amount: float, cap: float) -> str:
        """Unknown/failed calls retain their reservation. No automatic retry can overspend the ledger."""
        call_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute("SELECT COALESCE(SUM(reserved_cny),0) FROM model_calls").fetchone()[0]
            if total + amount > min(cap, 300):
                raise RuntimeError("MODEL_BUDGET_EXHAUSTED")
            db.execute(
                "INSERT INTO model_calls(id,job,reserved_cny,status,model,created) VALUES(?,?,?,'RESERVED',?,?)",
                (call_id, job, amount, model, time.time()),
            )
        return call_id

    def call_usage(self, call_id: str, usage: dict, latency_ms: float) -> None:
        upper = cny_upper(usage)
        with self.connect() as db:
            db.execute(
                "UPDATE model_calls SET status=?,input_tokens=?,output_tokens=?,cached_tokens=?,latency_ms=? WHERE id=?",
                (
                    "REPORTED" if upper is not None else "UNKNOWN_USAGE",
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                    usage.get("prompt_cache_hit_tokens"),
                    latency_ms,
                    call_id,
                ),
            )
            if upper is not None:
                db.execute("UPDATE model_calls SET reserved_cny=? WHERE id=?", (upper, call_id))
                db.execute(
                    "INSERT INTO events(job,kind,data,created) SELECT job,'budget_settled',?,? FROM model_calls WHERE id=?",
                    (
                        json.dumps(
                            {
                                "call": call_id,
                                "cny_upper": upper,
                                "method": "official peak CNY rate +20%, round up; not actual invoice",
                                "pricing_date": "2026-11-05",
                            }
                        ),
                        time.time(),
                        call_id,
                    ),
                )

    def call_not_sent(self, call_id: str, reason: str) -> None:
        with self.connect() as db:
            row = db.execute(
                "SELECT job,reserved_cny FROM model_calls WHERE id=? AND status='RESERVED'", (call_id,)
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE model_calls SET status='NOT_SENT_CONNECT',reserved_cny=0 WHERE id=?", (call_id,)
                )
                db.execute(
                    "INSERT INTO events(job,kind,data,created) VALUES(?,?,?,?)",
                    (
                        row["job"],
                        "budget_reservation_released",
                        json.dumps({"call": call_id, "reason": reason, "released_cny": row["reserved_cny"]}),
                        time.time(),
                    ),
                )

    def preference(self, owner: str, key: str, value: str | None, *, confirmed: bool) -> None:
        if not confirmed:
            raise PermissionError("Long-term memory requires explicit user confirmation")
        with self.connect() as db:
            if value is None:
                db.execute("DELETE FROM preferences WHERE owner=? AND key=?", (owner, key))
            else:
                db.execute(
                    "INSERT INTO preferences VALUES(?,?,?) ON CONFLICT(owner,key) DO UPDATE SET value=excluded.value",
                    (owner, key, value),
                )

    def preferences(self, owner: str) -> dict:
        with self.connect() as db:
            return dict(db.execute("SELECT key,value FROM preferences WHERE owner=?", (owner,)).fetchall())

    def propose(self, job: str, plan: dict) -> str:
        body = json.dumps(plan, sort_keys=True, ensure_ascii=False)
        plan_hash = hashlib.sha256(body.encode()).hexdigest()
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO approvals(job,plan_hash,plan,expires) VALUES(?,?,?,?)",
                (job, plan_hash, body, time.time() + 1800),
            )
        return plan_hash

    def decide(self, job: str, plan_hash: str, approved: bool) -> None:
        with self.connect() as db:
            count = db.execute(
                "UPDATE approvals SET decision=? WHERE job=? AND plan_hash=? AND decision IS NULL AND expires>?",
                ("APPROVED" if approved else "REJECTED", job, plan_hash, time.time()),
            ).rowcount
            if count != 1:
                raise ValueError("Approval is missing, expired, or already decided")

    def approval(self, job: str, plan_hash: str) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM approvals WHERE job=? AND plan_hash=?", (job, plan_hash)
            ).fetchone()
        if not row:
            raise ValueError("Unknown approval")
        return dict(row)
