import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from conftest import archive

from repo_agent.repository import Repository
from repo_agent.retrieval import Embeddings, HybridSearch
from repo_agent.settings import Settings
from repo_agent.store import Store

pytestmark = pytest.mark.skipif(
    os.environ.get("SEARCH_IT") != "true", reason="Requires real ES and cached multilingual CPU ONNX weights"
)


async def test_real_incremental_vectors_failed_publication_and_chinese_query(tmp_path, monkeypatch):
    owner = "index-lab-" + uuid.uuid4().hex
    workspace = "workspace"
    store = Store(tmp_path)
    repo = Repository(store)
    real = Embeddings(Settings(data_dir=Path(".local"), embedding_enabled=True))

    class Tracking:
        model_name = real.model_name
        texts = 0

        def encode(self, texts):
            self.texts += len(texts)
            return real.encode(texts)

    vectors = Tracking()
    cfg = Settings(data_dir=tmp_path, embedding_enabled=True)
    search = HybridSearch(cfg, store, vectors)
    await search.setup()
    stages = {}
    try:

        def ingest(sha, version):
            return repo.ingest(
                owner,
                workspace,
                "https://github.com/example/incremental",
                "" + sha * 40,
                archive(
                    {
                        "README.md": f"项目安装运行环境需要Python {version}。支持Windows与Linux。\n",
                        "stable.py": "def stable_add(a,b):\n    return a+b\n",
                    }
                ),
            )

        a = ingest("a", "3.12")
        before = vectors.texts
        await search.index_snapshot(owner, workspace, a["id"])
        stages["first_encoded"] = vectors.texts - before
        assert stages["first_encoded"] == 2
        b = ingest("b", "3.13")
        before = vectors.texts
        await search.index_snapshot(owner, workspace, b["id"])
        stages["second_encoded"] = vectors.texts - before
        assert stages["second_encoded"] == 1
        found = await search.search(owner, workspace, b["id"], "安装运行环境", 2, "vector")
        assert any(r["path"] == "README.md" and "3.13" in r["content"] for r in found)
        with store.connect() as db:
            stable = db.execute(
                "SELECT digest FROM chunks WHERE snapshot=? AND path='stable.py'", (b["id"],)
            ).fetchone()[0]
        cache = (
            tmp_path
            / "vector-cache"
            / (hashlib.sha256((real.model_name + stable).encode()).hexdigest() + ".json")
        )
        cache.write_text("{partial", encoding="utf-8")
        c = ingest("c", "3.14")
        original = search.es.bulk

        async def fail_after_write(**kwargs):
            await original(**kwargs)
            return {"errors": True}

        monkeypatch.setattr(search.es, "bulk", fail_after_write)
        before = vectors.texts
        with pytest.raises(RuntimeError, match="INDEX_PARTIAL_FAILURE"):
            await search.index_snapshot(owner, workspace, c["id"])
        stages["corrupt_cache_and_changed_encoded"] = vectors.texts - before
        assert stages["corrupt_cache_and_changed_encoded"] == 2
        with pytest.raises(ValueError, match="atomically published"):
            await search.search(owner, workspace, c["id"], "Python", 2, "bm25")
        old = await search.search(owner, workspace, a["id"], "Python", 2, "bm25")
        assert any("3.12" in r["content"] for r in old)
        monkeypatch.setattr(search.es, "bulk", original)
        before = vectors.texts
        await search.index_snapshot(owner, workspace, c["id"])
        stages["retry_encoded"] = vectors.texts - before
        assert stages["retry_encoded"] == 0
        after = await search.search(owner, workspace, c["id"], "Python", 2, "bm25")
        assert any("3.14" in r["content"] for r in after) and all(r["snapshot"] == c["id"] for r in after)
        with pytest.raises(PermissionError):
            await search.search("other-owner", workspace, c["id"], "Python")
        result = {
            "status": "PASS",
            "real_model": real.model_name,
            "encoder": "CPU ONNX multilingual",
            "index": search.index,
            "encoding_counts": stages,
            "unchanged_vector_reused": True,
            "corrupt_cache_recomputed": True,
            "partial_version_not_visible": True,
            "old_commit_unchanged": True,
            "chinese_query_returns_versioned_readme": True,
            "cross_owner_denied": True,
            "scope": "Three synthetic two-file snapshots, actual ES and actual encoder. Publication fault injected after a real ES bulk write; not a broad multilingual quality benchmark or a full repository incremental AST build.",
        }
        Path(".local/incremental_search_probe.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
    finally:
        await search.es.delete_by_query(index=search.index, query={"term": {"owner": owner}}, refresh=True)
        await search.close()
