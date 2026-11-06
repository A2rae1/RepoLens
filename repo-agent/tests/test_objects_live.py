import hashlib
import os
import uuid

import pytest

from repo_agent.objects import PART_SIZE, Objects
from repo_agent.settings import Settings
from repo_agent.store import Store

pytestmark = pytest.mark.skipif(
    os.environ.get("OBJECT_IT") != "true", reason="Requires independent real S3-compatible service"
)


def test_real_multipart_resume_hash_owner_and_content_dedupe(tmp_path):
    cfg = Settings(data_dir=tmp_path)
    store = Store(tmp_path)
    objects = Objects(cfg, store)
    objects.setup()
    # Deterministic non-private bytes, >5MiB to force at least two real S3 parts.
    data = bytes(range(251)) * 22000
    digest = hashlib.sha256(data).hexdigest()
    owner = "object-it-" + uuid.uuid4().hex
    upload = objects.begin(owner, "workspace", digest, len(data))
    first = data[:PART_SIZE]
    objects.part(owner, upload["id"], 1, first, hashlib.sha256(first).hexdigest())
    # A new manager/connection discovers completed parts after a simulated client disconnect.
    resumed = Objects(cfg, Store(tmp_path))
    assert resumed.status(owner, upload["id"])["parts"] == [{"part": 1, "size": PART_SIZE}]
    with pytest.raises(PermissionError):
        resumed.status("different-owner", upload["id"])
    last = data[PART_SIZE:]
    with pytest.raises(ValueError, match="CHECKSUM"):
        resumed.part(owner, upload["id"], 2, last, "0" * 64)
    resumed.part(owner, upload["id"], 2, last, hashlib.sha256(last).hexdigest())
    assert resumed.complete(owner, upload["id"])["status"] == "COMPLETED"
    assert resumed.complete(owner, upload["id"])["status"] == "COMPLETED"
    assert resumed.download(owner, upload["id"]) == data
    assert resumed.begin(owner, "workspace", digest, len(data))["id"] == upload["id"]
    artifact = resumed.artifact(owner, "workspace", "job", "report", {"answer": "real object store check"})
    assert resumed.artifacts(owner, "job")[0]["id"] == artifact["id"]
    assert resumed.artifacts("different-owner", "job") == []


def test_completed_staging_is_recoverable_after_metadata_crash(tmp_path):
    cfg = Settings(data_dir=tmp_path)
    store = Store(tmp_path)
    objects = Objects(cfg, store)
    objects.setup()
    data = b"recovery-fixture"
    digest = hashlib.sha256(data).hexdigest()
    upload = objects.begin("recovery-" + uuid.uuid4().hex, "workspace", digest, len(data))
    owner = objects.store.connect()
    # Fetch the owner from our test record, never credentials.
    with owner as db:
        row = dict(db.execute("SELECT * FROM uploads WHERE id=?", (upload["id"],)).fetchone())
    objects.part(row["owner"], row["id"], 1, data, digest)
    with store.connect() as db:
        db.execute("UPDATE uploads SET status='ASSEMBLING' WHERE id=?", (row["id"],))
    parts = objects.s3.list_parts(Bucket=objects.bucket, Key=row["staging_key"], UploadId=row["upload_id"])[
        "Parts"
    ]
    objects.s3.complete_multipart_upload(
        Bucket=objects.bucket,
        Key=row["staging_key"],
        UploadId=row["upload_id"],
        MultipartUpload={"Parts": [{"PartNumber": p["PartNumber"], "ETag": p["ETag"]} for p in parts]},
    )
    # Server restarts with an assembled object and unfinished local metadata.
    recovered = Objects(cfg, Store(tmp_path))
    assert recovered.complete(row["owner"], row["id"])["status"] == "COMPLETED"
    assert recovered.download(row["owner"], row["id"]) == data
