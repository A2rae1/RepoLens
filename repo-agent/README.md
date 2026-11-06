# RepoLens 开源项目调研与复现Agent

固定公开GitHub仓库和40位commit，按版本归档与证据检索，动态工具取证→必要时人工审批→受限检查→引用报告。技术：Python3.12/FastAPI/Pydantic/LangGraph、DeepSeek、官方SQLite/Postgres saver、ES/CPU Embedding、MCP、RustFS/S3和Docker执行器。Java控制面负责身份/归属/任务状态/幂等/租约/陈旧回写防护；模型不直接改业务数据库。

## 启动

见工作区`docs/INTEGRATION.md`。`uv sync --frozen`安装主依赖，密钥只放本目录.env（公共例子.env.example），LIVE_MODEL_ENABLED默认false。累计300元硬上限，预算预留含失败不确定调用，不能当账单。日常Compose镜像默认FTS；真实ES/向量专项使用`uv sync --extra embedding --frozen`和原生`agent-start.ps1 -Search`，不要声称基础镜像已包含Embedding模型。

`uv run pytest -q`只收集本工程tests；真实依赖条件跳过另列。`uv run ruff check src tests scripts evaluation`检查源码。跨服务实测用工作区agent-e2e脚本，真实付费、工程审批与本人学习验收分开。Exact依赖见uv.lock，来源版本与许可见`docs/THIRD_PARTY_NOTICES.md`。

## 已实现的边界

- GitHub固定域名/路径/SHA与限量ZIP读取，不直接解压不可信压缩包到主机；仅白名单文本，当前.ini/.cfg等未纳入，不能把没索引到说成全仓没有。
- FTS基线/ES BM25/多语言CPU向量/RRF/重排可对照；内容+模型向量缓存复用，完整bulk后才发布版本marker；符号AST精确位置与模型引用校验。跨版本元数据仍重建，不冒称全量AST增量编译。
- LangGraph有步数/Token/活跃任务限制和持久化恢复；按需Skills限制工具scope，SSE事件ID回放；偏好隔离可删，父轮证据摘要有字节预算。
- 审批绑定计划哈希、不可变镜像ID、期限和白名单recipe；Docker子容器禁网、只读、非root、CPU/内存/PID/时间/输出限额，不持有Docker socket或主机密钥。可信编排器本身持有Docker接口，不是任意恶意代码强沙箱。
- S3报告归档、最多12MB的ZIP分片/状态续传/摘要校验/owner隔离。content JSON是小文件兼容通道，有base64开销，不是GB下载方案。
- MCP v1.x stdio协议发现/调用，PythonSDK和官方Inspector两个真实客户端验证；第二客户端1.0.4兼容本机Node版本，未升级全局Node。

## 评测与复现边界

80条Click8.1.8固定SHA开发集，AI编制并标64dev/16development-holdout，多轮已查看，不是盲测/独立人类评测。V6自动55/56、AI语义20/24，共75/80定义标准；V7六坏例4通过是单独回归，不能拼新80成绩。仍有无证据全局否定、分支混合等语义失败，引用存在不代表结论必真。

40查询检索对比BM25 Recall@5=.775、hybrid=.6375、rerank=.75（单仓库/AI路径标签），不宣称融合必优。固定Click受限完整pytest实测628PASS/21SKIP/1XFAIL，AST_OK只代表语法检查，不代表兼容所有Python版本或复现所有仓库。

开发验证范围见docs/VERIFICATION.md；运行数据保存在本机.local，不随源码发布。源代码由AI实现并复用框架，不冒领上游能力，
