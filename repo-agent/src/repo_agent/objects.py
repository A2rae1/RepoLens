"""S3-compatible multipart uploads with owner isolation, resumable part listing and SHA256 verification."""

import hashlib
import json
import math
import time
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .settings import Settings
from .store import Store

PART_SIZE = 5 * 1024 * 1024


class Objects:
    def __init__(self, cfg: Settings, store: Store):
        if not cfg.object_secret_key:
            raise RuntimeError("OBJECT_STORAGE_NOT_CONFIGURED")
        self.store = store
        self.bucket = "repolens-artifacts"
        self.s3 = boto3.client(
            "s3",
            endpoint_url=cfg.object_url,
            aws_access_key_id=cfg.object_access_key,
            aws_secret_access_key=cfg.object_secret_key,
            region_name="us-east-1",
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 2},
                connect_timeout=3,
                read_timeout=20,
                s3={"addressing_style": "path"},
            ),
        )
        with store.connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS uploads (
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,workspace TEXT NOT NULL,sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,staging_key TEXT NOT NULL,upload_id TEXT NOT NULL,
                status TEXT NOT NULL,object_key TEXT,created REAL NOT NULL
            );CREATE INDEX IF NOT EXISTS ix_upload_owner ON uploads(owner,workspace,sha256,status);
            CREATE TABLE IF NOT EXISTS object_artifacts(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,workspace TEXT NOT NULL,job TEXT NOT NULL,
                kind TEXT NOT NULL,object_key TEXT NOT NULL,sha256 TEXT NOT NULL,size INTEGER NOT NULL
            );""")

    def setup(self):
        buckets = {b["Name"] for b in self.s3.list_buckets()["Buckets"]}
        if self.bucket not in buckets:
            self.s3.create_bucket(Bucket=self.bucket)
        self.s3.put_bucket_lifecycle_configuration(
            Bucket=self.bucket,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "ID": "abort-incomplete",
                        "Status": "Enabled",
                        "Filter": {"Prefix": ""},
                        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
                    }
                ]
            },
        )

    def owned(self, owner: str, upload: str) -> dict:
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM uploads WHERE id=? AND owner=?", (upload, owner)).fetchone()
        if not row:
            raise PermissionError("Upload is absent or outside this account")
        return dict(row)

    def begin(self, owner: str, workspace: str, digest: str, size: int) -> dict:
        if (
            size < 1
            or size > 12_000_000
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("Upload must have a SHA256 and be <=12MB")
        with self.store.connect() as db:
            previous = db.execute(
                "SELECT * FROM uploads WHERE owner=? AND workspace=? AND sha256=? AND size=? AND status IN ('UPLOADING','COMPLETED') ORDER BY created DESC LIMIT 1",
                (owner, workspace, digest, size),
            ).fetchone()
        if previous:
            return self.status(owner, previous["id"]) | {"reused": True}
        identifier = uuid.uuid4().hex
        prefix = hashlib.sha256(f"{owner}:{workspace}".encode()).hexdigest()
        staging = f"{prefix}/staging/{identifier}"
        created = self.s3.create_multipart_upload(
            Bucket=self.bucket, Key=staging, ContentType="application/zip"
        )
        try:
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO uploads VALUES(?,?,?,?,?,?,?,'UPLOADING',NULL,?)",
                    (identifier, owner, workspace, digest, size, staging, created["UploadId"], time.time()),
                )
        except BaseException:
            self.s3.abort_multipart_upload(Bucket=self.bucket, Key=staging, UploadId=created["UploadId"])
            raise
        return self.status(owner, identifier)

    def status(self, owner: str, upload: str) -> dict:
        row = self.owned(owner, upload)
        parts = []
        if row["status"] == "UPLOADING":
            result = self.s3.list_parts(Bucket=self.bucket, Key=row["staging_key"], UploadId=row["upload_id"])
            parts = [{"part": p["PartNumber"], "size": p["Size"]} for p in result.get("Parts", [])]
        return {
            "id": upload,
            "status": row["status"],
            "sha256": row["sha256"],
            "size": row["size"],
            "part_size": PART_SIZE,
            "parts": parts,
        }

    def part(self, owner: str, upload: str, number: int, data: bytes, digest: str) -> dict:
        row = self.owned(owner, upload)
        count = math.ceil(row["size"] / PART_SIZE)
        expected = PART_SIZE if number < count else row["size"] - (count - 1) * PART_SIZE
        if row["status"] != "UPLOADING" or number < 1 or number > count or len(data) != expected:
            raise ValueError("Unexpected part number, size or upload state")
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("PART_CHECKSUM_MISMATCH")
        result = self.s3.upload_part(
            Bucket=self.bucket,
            Key=row["staging_key"],
            UploadId=row["upload_id"],
            PartNumber=number,
            Body=data,
        )
        return {"part": number, "etag": result["ETag"], "sha256": digest}

    def complete(self, owner: str, upload: str) -> dict:
        row = self.owned(owner, upload)
        if row["status"] == "COMPLETED":
            return self.status(owner, upload)
        # This application never uploads directly to the final content-addressed key.
        # A bad checksum can only invalidate its own staging object.
        try:
            parts = self.s3.list_parts(
                Bucket=self.bucket, Key=row["staging_key"], UploadId=row["upload_id"]
            ).get("Parts", [])
        except ClientError as exc:
            if row["status"] != "ASSEMBLING" or exc.response["Error"]["Code"] != "NoSuchUpload":
                raise
            # A crash may occur after S3 assembled staging but before our metadata commit.
            self.s3.head_object(Bucket=self.bucket, Key=row["staging_key"])
            parts = None
        if parts is not None:
            if (
                len(parts) != math.ceil(row["size"] / PART_SIZE)
                or sum(p["Size"] for p in parts) != row["size"]
            ):
                raise ValueError("UPLOAD_INCOMPLETE")
            with self.store.connect() as db:
                db.execute(
                    "UPDATE uploads SET status='ASSEMBLING' WHERE id=? AND status='UPLOADING'", (upload,)
                )
            self.s3.complete_multipart_upload(
                Bucket=self.bucket,
                Key=row["staging_key"],
                UploadId=row["upload_id"],
                MultipartUpload={
                    "Parts": [{"PartNumber": p["PartNumber"], "ETag": p["ETag"]} for p in parts]
                },
            )
        response = self.s3.get_object(Bucket=self.bucket, Key=row["staging_key"])
        checksum = hashlib.sha256()
        try:
            while chunk := response["Body"].read(262144):
                checksum.update(chunk)
        finally:
            response["Body"].close()
        if checksum.hexdigest() != row["sha256"]:
            self.s3.delete_object(Bucket=self.bucket, Key=row["staging_key"])
            with self.store.connect() as db:
                db.execute("UPDATE uploads SET status='CHECKSUM_FAILED' WHERE id=?", (upload,))
            raise ValueError("OBJECT_CHECKSUM_MISMATCH")
        prefix = hashlib.sha256(f"{owner}:{row['workspace']}".encode()).hexdigest()
        final = f"{prefix}/sha256/{row['sha256']}.zip"
        self.s3.copy_object(
            Bucket=self.bucket, Key=final, CopySource={"Bucket": self.bucket, "Key": row["staging_key"]}
        )
        with self.store.connect() as db:
            db.execute("UPDATE uploads SET status='COMPLETED',object_key=? WHERE id=?", (final, upload))
        self.s3.delete_object(Bucket=self.bucket, Key=row["staging_key"])
        return self.status(owner, upload)

    def download(self, owner: str, upload: str) -> bytes:
        row = self.owned(owner, upload)
        if row["status"] != "COMPLETED":
            raise ValueError("Object has not been verified")
        response = self.s3.get_object(Bucket=self.bucket, Key=row["object_key"])
        try:
            content = response["Body"].read(12_000_001)
        finally:
            response["Body"].close()
        if len(content) != row["size"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError("STORED_OBJECT_CHECKSUM_MISMATCH")
        return content

    def artifact(self, owner: str, workspace: str, job: str, kind: str, body: dict) -> dict:
        payload = json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
        if len(payload) > 1_000_000:
            raise ValueError("Artifact exceeds size limit")
        digest = hashlib.sha256(payload).hexdigest()
        prefix = hashlib.sha256(f"{owner}:{workspace}".encode()).hexdigest()
        key = f"{prefix}/artifacts/{job}/{kind}-{digest}.json"
        identifier = hashlib.sha256(f"{owner}:{workspace}:{job}:{kind}:{digest}".encode()).hexdigest()
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=payload, ContentType="application/json")
        with self.store.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO object_artifacts VALUES(?,?,?,?,?,?,?,?)",
                (identifier, owner, workspace, job, kind, key, digest, len(payload)),
            )
        return {"id": identifier, "sha256": digest, "size": len(payload), "kind": kind}

    def artifacts(self, owner: str, job: str) -> list[dict]:
        with self.store.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,kind,sha256,size FROM object_artifacts WHERE owner=? AND job=?", (owner, job)
                )
            ]

    def read_artifact(self, owner: str, job: str, identifier: str) -> bytes:
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM object_artifacts WHERE id=? AND owner=? AND job=?", (identifier, owner, job)
            ).fetchone()
        if not row:
            raise PermissionError("Artifact absent or forbidden")
        response = self.s3.get_object(Bucket=self.bucket, Key=row["object_key"])
        try:
            payload = response["Body"].read(1_000_001)
        finally:
            response["Body"].close()
        if len(payload) != row["size"] or hashlib.sha256(payload).hexdigest() != row["sha256"]:
            raise ValueError("ARTIFACT_CHECKSUM_MISMATCH")
        return payload
