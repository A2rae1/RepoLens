# RepoLens Agent

根据GitHub仓库、完整commit和问题开展源码调研，调用检索与文件工具生成引用报告，支持多轮追问和审批后的Python验证。

## 功能

- 版本快照、FTS与Elasticsearch检索、Embedding和检索缓存。
- LangGraph工具循环、按需Skills、上下文摘要与工作区偏好。
- 持久化检查点、任务恢复、取消、执行预算和事件流。
- 计划审批、Python语法/单元测试/pytest运行与结果归档。
- S3资料分片续传、完整性校验和报告导出。
- MCP检索接口、离线评测与用量统计。

技术栈：Python3.12、FastAPI、Pydantic、LangGraph、DeepSeek、PostgreSQL、SQLite、Elasticsearch、MCP、RustFS/S3和Docker。

## 开发与验证

```powershell
uv sync --frozen
uv run pytest -q
uv run ruff check src tests scripts evaluation
```

完整应用的构建、模型配置、账号和运行入口见仓库根目录README。repo-control提供Java身份与任务接口；本服务API端口8092，Web入口8094。
