from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8-sig", extra="ignore")
    data_dir: Path = Path(".local")
    deepseek_api_key: str = Field(default="", repr=False)
    deepseek_model: str = "deepseek-flash"
    live_model_enabled: bool = False
    model_budget_cny: float = Field(default=300, gt=0, le=300)
    # Conservative budget reservations are distinct from measured provider charges.
    reserve_cny_per_call: float = Field(default=1, ge=1)
    max_output_tokens: int = Field(default=1600, ge=100, le=4096)
    max_steps: int = Field(default=10, ge=1, le=20)
    request_timeout: float = 45
    checkpoint_url: str = ""
    es_url: str = "http://127.0.0.1:19200"
    redis_url: str = "redis://127.0.0.1:16379/1"
    object_url: str = "http://127.0.0.1:19000"
    object_access_key: str = "repoagent"
    object_secret_key: str = Field(default="", repr=False)
    object_enabled: bool = False
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_enabled: bool = False
    search_backend: str = "fts"
    # BM25 beat RRF on the pinned symbol/config-heavy development corpus.
    # Hybrid remains available for semantically phrased queries and explicit comparisons.
    search_strategy: str = Field(default="bm25", pattern="^(bm25|vector|hybrid)$")
    rerank_enabled: bool = False
    docker_executable: str = "docker"
    executor_image: str = "repolens-runner:py312-v1"
    executor_enabled: bool = False
    executor_work_dir: Path | None = None
    executor_volume: str = Field(default="", pattern=r"^[a-zA-Z0-9_.-]*$")
    control_url: str = "http://127.0.0.1:8090"
    control_token: str = Field(default="", repr=False)
    agent_internal_secret: str = Field(default="", repr=False)
    otlp_endpoint: str = ""
    metrics_password: str = Field(default="", repr=False)

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
