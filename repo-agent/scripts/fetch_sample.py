import asyncio
import json

from repo_agent.repository import Repository
from repo_agent.settings import Settings
from repo_agent.store import Store


async def main():
    cfg = Settings()
    store = Store(cfg.data_dir)
    # Annotated tag peeled to its actual commit, independently checked via public git ls-remote.
    # Fixed manifest avoids unauthenticated GitHub API rate limits; it does not silently follow a moving branch.
    sha = "934813e4d421071a1b3db3973c02fe2721359a6e"
    snapshot = await Repository(store).fetch(
        "eval-owner", "eval-workspace", "https://github.com/pallets/click", sha
    )
    output = {
        "repo": "https://github.com/pallets/click",
        "tag": "8.1.8",
        "commit": sha,
        "snapshot": snapshot["id"],
        "provenance": "Public upstream repository; retrieved 2026-11-05",
        "license": "BSD-3-Clause (verify snapshot LICENSE.txt)",
        "purpose": "Pinned real-repository evidence benchmark",
    }
    path = cfg.data_dir / "sample_manifest.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
