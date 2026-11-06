"""One explicitly authorized, bounded live call. Never print credentials or request headers."""

import asyncio
import json

from repo_agent.model import DeepSeekModel
from repo_agent.settings import Settings
from repo_agent.store import Store
from repo_agent.tools import tool_schemas


async def main():
    cfg = Settings(max_output_tokens=100)
    cfg.prepare()
    store = Store(cfg.data_dir)
    result = await DeepSeekModel(cfg, store).complete(
        "live-connectivity-check",
        [{"role": "user", "content": "这是API连通性测试。不要调用工具，只回复OK。"}],
        tool_schemas(),
    )
    print(
        json.dumps(
            {"status": "CONNECTED", "model": cfg.deepseek_model, "reply": result.get("content", "")[:100]},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
