import hashlib
import json
import zipfile
from pathlib import Path


def freeze(root: Path, cfg, extra: dict | None = None):
    paths = (
        sorted(Path("src/repo_agent").glob("*.py"))
        + sorted(Path("evaluation").glob("*.py"))
        + [Path("uv.lock"), Path("evaluation/cases.jsonl")]
    )
    hashes = {str(p).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    metadata = {
        "files": hashes,
        "model": cfg.deepseek_model,
        "max_steps": cfg.max_steps,
        "max_output_tokens": cfg.max_output_tokens,
        "search_backend": cfg.search_backend,
        "search_strategy": cfg.search_strategy,
        "parameters": extra or {},
    }
    digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    metadata["experiment_digest"] = digest
    target = root / "provenance.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != metadata:
        raise RuntimeError("Experiment code/config changed; use a new output directory and run-id")
    target.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    snapshot = root / "source-snapshot.zip"
    if not snapshot.exists():
        with zipfile.ZipFile(snapshot, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != hashes[str(path).replace("\\", "/")]:
                    raise RuntimeError("Source changed while freezing experiment")
                archive.writestr(str(path).replace("\\", "/"), content)
    return metadata
