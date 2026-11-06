import asyncio
import json

from repo_agent.retrieval import Embeddings, HybridSearch
from repo_agent.settings import Settings
from repo_agent.store import Store


async def main():
    cfg = Settings(embedding_enabled=True)
    store = Store(cfg.data_dir)
    manifest = json.loads((cfg.data_dir / "sample_manifest.json").read_text(encoding="utf-8"))
    embeddings = Embeddings(cfg)
    search = HybridSearch(cfg, store, embeddings)
    await search.setup()
    try:
        await search.index_snapshot("eval-owner", "eval-workspace", manifest["snapshot"])
        results = {}
        for strategy in ["bm25", "vector", "hybrid"]:
            found = await search.search(
                "eval-owner",
                "eval-workspace",
                manifest["snapshot"],
                "Python version requirements",
                5,
                strategy,
            )
            assert found
            results[strategy] = [
                {"path": item["path"], "id": item["id"], "score": item["score"]} for item in found
            ]
        try:
            await search.search("other-owner", "eval-workspace", manifest["snapshot"], "Python", 5)
            raise AssertionError("Cross-user access was not rejected")
        except PermissionError:
            pass
        report = {
            "status": "PASS",
            "model": cfg.embedding_model,
            "snapshot": manifest["snapshot"],
            "retrieval": results,
            "cross_owner": "DENIED",
            "scope": "one fixed real repo; not Recall@K benchmark",
        }
        (cfg.data_dir / "search_smoke.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps({"status": "PASS", "strategies": list(results), "cross_owner": "DENIED"}))
    finally:
        await search.close()


if __name__ == "__main__":
    asyncio.run(main())
