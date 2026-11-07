"""Approval decisions and their durable delivery share one SQLite transaction."""

import hashlib
import json
import time
import uuid


class Approvals:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(approvals)")}
            if "nonce" not in columns:
                db.execute("ALTER TABLE approvals ADD COLUMN nonce TEXT NOT NULL DEFAULT ''")
            db.execute("""CREATE TABLE IF NOT EXISTS approval_deliveries(
                job TEXT NOT NULL,plan_hash TEXT NOT NULL,nonce TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',PRIMARY KEY(job,plan_hash,nonce)
            )""")

    def propose(self, job: str, plan: dict) -> str:
        body = json.dumps(plan, sort_keys=True, ensure_ascii=False)
        plan_hash = hashlib.sha256(body.encode()).hexdigest()
        with self.store.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO approvals(job,plan_hash,plan,expires) VALUES(?,?,?,?)",
                (job, plan_hash, body, time.time() + 1800),
            )
        return plan_hash

    def get(self, job: str, plan_hash: str) -> dict:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM approvals WHERE job=? AND plan_hash=?", (job, plan_hash)
            ).fetchone()
        if not row:
            raise ValueError("Unknown approval")
        return dict(row)

    def decide(
        self, job: str, plan_hash: str, approved: bool, nonce: str = "", *, deliver: bool = False
    ) -> None:
        decision = "APPROVED" if approved else "REJECTED"
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM approvals WHERE job=? AND plan_hash=?", (job, plan_hash)
            ).fetchone()
            if not row or row["nonce"] != nonce:
                raise ValueError("Approval is missing or was renewed; refresh the plan")
            if row["decision"] and row["decision"] != decision:
                raise ValueError("A recorded approval decision cannot be reversed")
            if not row["decision"] and approved and row["expires"] <= time.time():
                raise ValueError("Approval expired; renew and review the plan before approving")
            db.execute(
                "UPDATE approvals SET decision=? WHERE job=? AND plan_hash=?",
                (decision, job, plan_hash),
            )
            # Replaying the same decision never resets a delivered record or its expiry.
            if deliver:
                db.execute(
                    "INSERT OR IGNORE INTO approval_deliveries(job,plan_hash,nonce) VALUES(?,?,?)",
                    (job, plan_hash, nonce),
                )

    def renew(self, job: str, plan_hash: str) -> dict:
        with self.store.connect() as db:
            changed = db.execute(
                "UPDATE approvals SET nonce=?,expires=? WHERE job=? AND plan_hash=? AND decision IS NULL AND expires<=?",
                (uuid.uuid4().hex, time.time() + 1800, job, plan_hash, time.time()),
            ).rowcount
            if changed != 1:
                raise ValueError("Only an expired, undecided plan can be renewed")
        return self.get(job, plan_hash)

    def pending(self) -> list[dict]:
        with self.store.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM approval_deliveries WHERE status='PENDING' LIMIT 50")
            ]

    def delivered(self, job: str, plan_hash: str, nonce: str, status: str = "DELIVERED"):
        with self.store.connect() as db:
            db.execute(
                "UPDATE approval_deliveries SET status=? WHERE job=? AND plan_hash=? AND nonce=?",
                (status, job, plan_hash, nonce),
            )
