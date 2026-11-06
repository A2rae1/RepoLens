"""Version-filtered Elasticsearch lexical + local ONNX vector retrieval. No fake embeddings."""

import asyncio
from collections import defaultdict

from elasticsearch import AsyncElasticsearch

from .settings import Settings
from .store import Store


class Embeddings:
    def __init__(self, cfg: Settings):
        if not cfg.embedding_enabled:
            raise RuntimeError("EMBEDDING_DISABLED")
        from fastembed import TextEmbedding

        self.model = TextEmbedding(
            model_name=cfg.embedding_model,
            cache_dir=str(cfg.data_dir / "models"),
            threads=2,
            providers=["CPUExecutionProvider"],
            cuda=False,
        )
        self.model_name = cfg.embedding_model

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self.model.embed(texts, batch_size=8)]


class HybridSearch:
    def __init__(self, cfg: Settings, store: Store, embeddings: Embeddings):
        self.cfg, self.store, self.embeddings = cfg, store, embeddings
        self.es = AsyncElasticsearch(cfg.es_url, request_timeout=15)
        # v2 separates model-specific ES document identities from canonical source IDs.
        self.index = "repolens-evidence-v2"

    async def setup(self):
        with self.store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS search_versions_v2(snapshot TEXT PRIMARY KEY,model TEXT NOT NULL)"
            )
        dimension = len((await asyncio.to_thread(self.embeddings.encode, ["dimension probe"]))[0])
        if not await self.es.indices.exists(index=self.index):
            with self.store.connect() as db:
                db.execute("DELETE FROM search_versions_v2")
            await self.es.indices.create(
                index=self.index,
                mappings={
                    "properties": {
                        "owner": {"type": "keyword"},
                        "workspace": {"type": "keyword"},
                        "snapshot": {"type": "keyword"},
                        "model": {"type": "keyword"},
                        "path": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
                        "content": {"type": "text"},
                        "vector": {
                            "type": "dense_vector",
                            "dims": dimension,
                            "index": True,
                            "similarity": "cosine",
                        },
                    }
                },
            )

    async def index_snapshot(self, owner: str, workspace: str, snapshot: str):
        self.store.snapshot(snapshot, owner, workspace)
        with self.store.connect() as db:
            rows = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM chunks WHERE snapshot=? ORDER BY path,start_line", (snapshot,)
                )
            ]
        # Stable content/model keys reuse vectors across commits; source IDs still remain version-specific.
        cache = self.cfg.data_dir / "vector-cache"
        cache.mkdir(exist_ok=True)
        import hashlib
        import json

        operations = []
        for row in rows:
            key = hashlib.sha256((self.embeddings.model_name + row["digest"]).encode()).hexdigest()
            path = cache / (key + ".json")
            try:
                vector = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(vector, list) or not vector:
                    raise ValueError("Invalid cached vector")
            except (FileNotFoundError, ValueError):
                vector = (await asyncio.to_thread(self.embeddings.encode, [row["content"]]))[0]
                import os
                import uuid

                temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
                try:
                    temp.write_text(json.dumps(vector), encoding="utf-8")
                    os.replace(temp, path)
                finally:
                    temp.unlink(missing_ok=True)
            operations += [
                {"index": {"_index": self.index, "_id": self.embeddings.model_name + ":" + row["id"]}},
                row
                | {
                    "owner": owner,
                    "workspace": workspace,
                    "model": self.embeddings.model_name,
                    "vector": vector,
                },
            ]
            if len(operations) >= 64:
                result = await self.es.bulk(operations=operations, refresh=False)
                if result["errors"]:
                    raise RuntimeError("INDEX_PARTIAL_FAILURE")
                operations = []
        if operations:
            result = await self.es.bulk(operations=operations, refresh=False)
            if result["errors"]:
                raise RuntimeError("INDEX_PARTIAL_FAILURE")
        await self.es.indices.refresh(index=self.index)
        # Mark visible only after every indexed chunk is available. Failed builds never become query targets.
        with self.store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS search_versions_v2(snapshot TEXT PRIMARY KEY,model TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO search_versions_v2 VALUES(?,?) ON CONFLICT(snapshot) DO UPDATE SET model=excluded.model",
                (snapshot, self.embeddings.model_name),
            )

    async def search(
        self, owner: str, workspace: str, snapshot: str, query: str, k: int = 5, strategy: str = "hybrid"
    ) -> list[dict]:
        self.store.snapshot(snapshot, owner, workspace)
        with self.store.connect() as db:
            visible = db.execute(
                "SELECT model FROM search_versions_v2 WHERE snapshot=?", (snapshot,)
            ).fetchone()
        if not visible or visible["model"] != self.embeddings.model_name:
            raise ValueError("Search version is not atomically published for this embedding model")
        filters = [
            {"term": {"owner": owner}},
            {"term": {"workspace": workspace}},
            {"term": {"snapshot": snapshot}},
            {"term": {"model": self.embeddings.model_name}},
        ]
        lexical, semantic = [], []
        if strategy in {"bm25", "hybrid"}:
            result = await self.es.search(
                index=self.index,
                size=20,
                query={
                    "bool": {
                        "filter": filters,
                        "must": [{"multi_match": {"query": query, "fields": ["path^3", "content"]}}],
                    }
                },
            )
            lexical = result["hits"]["hits"]
        if strategy in {"vector", "hybrid"}:
            vector = (await asyncio.to_thread(self.embeddings.encode, [query]))[0]
            result = await self.es.search(
                index=self.index,
                size=20,
                knn={
                    "field": "vector",
                    "query_vector": vector,
                    "k": 20,
                    "num_candidates": 100,
                    "filter": {"bool": {"filter": filters}},
                },
            )
            semantic = result["hits"]["hits"]
        scores, documents = defaultdict(float), {}
        for ranking in [lexical, semantic]:
            for rank, hit in enumerate(ranking):
                source = hit["_source"]
                if (
                    source["owner"] != owner
                    or source["workspace"] != workspace
                    or source["snapshot"] != snapshot
                ):
                    raise PermissionError("Unexpected cross-scope retrieval result")
                scores[hit["_id"]] += 1 / (60 + rank + 1)
                documents[hit["_id"]] = {key: value for key, value in source.items() if key != "vector"}
        return [
            documents[key] | {"score": scores[key], "retrieval": f"es_{strategy}_rrf"}
            for key in sorted(scores, key=scores.get, reverse=True)[: max(1, min(k, 10))]
        ]

    async def close(self):
        await self.es.close()


class Reranker:
    def __init__(self, cfg: Settings, model_name="Xenova/ms-marco-MiniLM-L-6-v2"):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model = TextCrossEncoder(
            model_name=model_name,
            cache_dir=str(cfg.data_dir / "models"),
            threads=2,
            providers=["CPUExecutionProvider"],
            cuda=False,
        )

    async def rank(self, query: str, evidence: list[dict], k: int = 5):
        scores = await asyncio.to_thread(
            lambda: list(self.model.rerank(query, [e["content"] for e in evidence], batch_size=4))
        )
        return [
            row | {"rerank_score": float(score)}
            for row, score in sorted(zip(evidence, scores), key=lambda pair: pair[1], reverse=True)[:k]
        ]
