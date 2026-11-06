import json

from repo_agent.retrieval import Embeddings
from repo_agent.settings import Settings

cfg = Settings(embedding_enabled=True)
model = Embeddings(cfg)
vectors = model.encode(["Python version requirements", "需要什么Python版本？"])
print(
    json.dumps(
        {
            "model": cfg.embedding_model,
            "dimensions": len(vectors[0]),
            "vectors": len(vectors),
            "provider": "CPUExecutionProvider",
            "gpu_required": False,
        }
    )
)
