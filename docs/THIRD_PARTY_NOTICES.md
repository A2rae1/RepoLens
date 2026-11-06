# 开源来源、版本与复用边界

核对：2026-11-06。两项目业务代码/测试/界面/脚本由AI按本工作区需求实现，没有整体fork CityHub、DoVideoAI、FunClip或其他成品。框架、SDK、镜像、模型和测试语料保留原来源；代码由AI写不表示本人独立手写或理解已通过。未给第三方文件统一改换许可证。

## 直接保留的文件

- `event-platform/src/main/resources/static/vendor`：Vue3.5.30及随附MIT许可，前端不是自行实现Vue框架。
- `infra/xxl-job/upstream-schema.sql`和LICENSE：来自XXL-JOB3.1.1，初始化适配/种子另在本项目脚本；官方[3.1.1许可](https://github.com/xuxueli/xxl-job/blob/3.1.1/LICENSE)为GPLv3，未把其改称Apache/MIT。
- `infra/k8s/metrics-server.upstream.yml`：官方[metrics-server0.9.1](https://github.com/kubernetes-sigs/metrics-server/releases/tag/v0.9.1)发布清单；生成的lab副本只加本地自签kubelet测试参数和镜像摘要，不修改上游原件。
- Click8.1.8源码是公开测试输入，固定commit `934813e4d421071a1b3db3973c02fe2721359a6e`、BSD-3-Clause；归档在私有.local快照并保留上游LICENSE.txt，不是我们实现的业务。pytest628通过是该固定样本运行，不是个人写了628项测试。

## Java与运行组件

坐标以event-platform/pom.xml、gateway/pom.xml及构建依赖为准。Java17目标，Spring Boot3.5.16，MyBatis-Plus3.5.18，RocketMQ client5.3.2，Redisson3.52.0，Nacos client/server3.3.0，springdoc2.8.17，XXL-JOB3.1.1；Gateway使用Cloud2025.0.3及管理的Gateway/LoadBalancer/Resilience4j。Spring、MyBatisPlus、RocketMQ、Nacos、Redisson为各自上游框架能力，不冒领实现其内部协议。

容器：MySQL8.4.9、Redis7.4.2、RocketMQ5.3.2、Postgres17.4、ES8.19.23、RustFS1.0.4；观测OTel collector/Tempo2.9.0/Prometheus3.7.3/Grafana12.3.0；实际digest记录compose、image-lock与证据。基础Java/Python/DockerCLI已锁摘要，其他部分组件锁版本标签，不能说全供应链不可变。DockerDesktop许可与组件许可分别适用。

Redis服务端7.4.2不是redis-py的MIT许可，遵循其[版本许可](https://github.com/redis/redis/blob/7.4.2/LICENSE.txt)的RSALv2/SSPLv1选择条款；ES镜像标注Elastic-License-2.0。RustFS1.0.4遵循[Apache2.0](https://github.com/rustfs/rustfs/blob/1.0.4/LICENSE)，实际使用S3兼容API，未安装MinIO。二进制/容器的发行版与依赖各自保留许可，不把所有组件笼统称“MIT开源”。本表是来源记录，不代替正式对外分发时的逐包许可审查。

## Python安装元数据（本机锁定环境）

以下版本/许可从本机distribution METADATA提取；精确传递依赖见uv.lock，不靠手填范围代替锁文件。

| 包 | 实际版本 | 声明许可 |
|---|---|---|
| fastapi | 0.162.0 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| pydantic | 2.14.3 | MIT |
| pydantic-settings | 2.16.2 | MIT |
| langgraph | 1.2.20 | MIT |
| langgraph-checkpoint-sqlite | 3.1.3 | MIT |
| langgraph-checkpoint-postgres | 3.2.0 | MIT |
| psycopg | 3.3.8 | LGPL-3.0-only |
| elasticsearch | 8.19.3 | Apache-2.0 |
| redis | 6.4.0 | MIT |
| boto3 | 1.43.124 | Apache-2.0 |
| mcp | 1.30.0 | MIT |
| fastembed | 0.9.1 | Apache-2.0 |
| onnxruntime | 1.31.1 | MIT License |
| opentelemetry-sdk | 1.45.2 | Apache-2.0 |
| httpx | 0.28.1 | BSD-3-Clause |
| ruff | 0.17.3 | MIT |

Embedding为sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2的CPU ONNX版本，模型权重/转换来源按FastEmbed下载及模型卡保留；不宣称自训练。DeepSeek是付费远程API，实际模型名与每次Token写账，密钥不在本表。

## 工具与贡献划分

官方MCP SDK1.x；第二客户端为Inspector1.0.4 CLI（本机Node24.15不足当前v2要求，使用维护线并保留package-lock）。Playwright用于无界面UI测试，不控制用户桌面；k6 2.3.0、kind0.33.0、kubectl1.35.8来自官方发行校验，K8s node1.35.8和metrics-server0.9.1固定digest。

上游提供：Web/事务/ORM/MQ/缓存/Agent图/检查点/MCP/对象协议/向量计算等基础。AI实现：票务状态/候补/Outbox协议、Java任务控制面、版本证据/工具/审批/恢复/引用/评测、配置与验证。本人当前已知贡献只限既有基础学习记录，项目理解/变更能力尚未验收，未来按真实学习证据更新。


Repository split: Java source is in A2rae1/EventFulfill; Python Agent source is in A2rae1/RepoLens. Historical joint verification is retained as historical evidence; new repository CI is verified separately.
