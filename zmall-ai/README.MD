# ZMall AI 服务工程

Python AI 服务层，包含 AI 随心搭（用户端）与 AI 模特（商家端）两大功能。

## 设计文档

AI 模块的开发遵循以下设计文档的推导顺序：

1. `docs/AI功能需求分析.md` — 需求分析：业务场景、用户故事、功能边界与验收标准
2. `docs/AI功能后端架构方案.md` — 架构设计：技术选型、服务划分、接口契约、稳定性设计
3. `docs/AI核心功能设计.md` — 详细设计：数据模型、核心流程、LangGraph 节点编排、MQ 消息格式、配额机制
4. `docs/AI功能前端设计方案.md` — 前端设计：双前端页面结构、组件、WebSocket 接入与状态管理

开发流程：需求分析 → 架构方案 → 核心功能设计 → 前端方案 → 代码实现。接口路径、DTO 字段、MQ routing key、Redis key、配额类型、超时阈值等实现细节均可从上述文档溯源。

## 工程结构

```
zmall-ai/
├── ai-models/           # AI 模特服务（端口 9000）
│   ├── app/
│   │   ├── api/         # 路由层（model / ws / search）
│   │   ├── core/        # 配置 / 安全 / 异常
│   │   ├── graphs/      # 工作流编排（single / multi_outfit / multi_pose）
│   │   ├── models/      # Pydantic 模型 + ORM
│   │   ├── services/    # 业务逻辑层
│   │   ├── schemas/     # 数据模型定义
│   │   ├── prompts/     # LLM 提示词模板
│   │   ├── subgraphs/   # 多 Agent 子图
│   │   └── main.py      # FastAPI 入口
│   └── scripts/         # 维护脚本
│
├── ai-outfit/           # AI 随心搭服务（端口 9001）
│   ├── app/
│   │   ├── api/         # 路由层（outfit_agent / outfit_product / ws）
│   │   ├── core/        # 配置 / 安全 / 异常
│   │   ├── graphs/      # LangGraph 工作流编排
│   │   ├── services/    # 业务逻辑层
│   │   ├── schemas/     # 数据模型定义
│   │   ├── prompts/     # LLM 提示词模板
│   │   ├── tools/       # Agent 工具
│   │   └── main.py      # FastAPI 入口
│   ├── scripts/         # 维护脚本（索引、对账）
│   └── logs/
│
└── shared/              # 共享模块
    ├── db_client/           # MySQL 连接池
    ├── qdrant_client/       # Qdrant 向量数据库
    ├── oss_client/          # 阿里云 OSS
    ├── model_client/        # AI 模型调用（文本 / 视觉 / VTON / 精修 / 向量编码）
    ├── mq_client/           # RabbitMQ 生产 / 消费
    ├── ws_manager/          # WebSocket 连接池
    ├── java_client/         # 调用 Java 微服务接口
    ├── nacos_register/      # Nacos 服务注册 / 心跳
    ├── nacos_discovery/     # Nacos 服务发现
    ├── distributed_lock/    # 分布式锁
    ├── external_services/   # 外部服务（价格平衡 / 库存 / 流行趋势 / 天气）
    ├── outfit_common/       # 搭配通用逻辑（品类校验 / 图像合成 / 会话计数）
    ├── metrics/             # 监控指标
    └── tools/               # 工具注册表
```

## 服务划分

| 服务 | 功能 | 特点 |
|------|------|------|
| `ai-outfit` | AI 随心搭 | 风格驱动、用户选定、商品驱动三种入口，LangGraph 多步推理，CPU 密集 |
| `ai-models` | AI 模特 | 单图 / 多姿势 / 多换装三种生成模式，链式换装 + LLM 多 Agent 决策，I/O 密集 |
| `shared` | 公共模块 | 两个 Python 服务与 Java 微服务、外部服务交互的公共能力 |

两个服务职责独立、无代码共享，仅共享 `shared` 模块与统一 credits 配额池。Java 负责交易与业务数据，Python 负责 AI 推理与向量检索，两者通过 RabbitMQ 与 HTTP 协作。

## 快速启动

```bash
# 1. 安装依赖
cd zmall-ai
pip install -r requirements.txt

# 2. 启动 ai-models（端口 9000，AI 模特）
cd ai-models
uvicorn app.main:app --host 0.0.0.0 --port 9000 --reload

# 3. 启动 ai-outfit（端口 9001，AI 随心搭）
cd ai-outfit
uvicorn app.main:app --host 0.0.0.0 --port 9001 --reload
```

## 环境变量

核心配置通过 `.env` 加载（`app/core/config.py` 的 BaseSettings 模型）。主要的本地基础设施地址：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `NACOS_SERVER` | 192.168.59.128:8848 | Nacos 地址 |
| `REDIS_HOST` | 192.168.59.128 | Redis 地址 |
| `REDIS_PORT` | 6379 | Redis 端口 |
| `REDIS_DB` | 0 | Redis 数据库 |
| `QDRANT_HOST` | 192.168.59.128 | Qdrant 地址 |
| `QDRANT_PORT` | 6333 | Qdrant 端口 |
| `RABBITMQ_HOST` | 192.168.59.128 | RabbitMQ 地址 |
| `MYSQL_HOST` | 192.168.59.128 | MySQL 地址 |

各服务的 AI 模型配置（模型名、API Key、地址）均位于各服务的 `app/core/config.py` 中，通过 `.env` 覆盖。

## 基础设施部署

zmall-ai 依赖以下基础设施（与 Java 微服务共用）：

| 组件 | 说明 |
|------|------|
| Nacos | 服务注册 / 发现，Python 通过 Open API 注册 |
| MySQL | 数据库（任务记录、衣橱、搭配记录、credits 账户等） |
| Redis | 缓存（任务状态、照片会话、credits 预扣、分布式锁） |
| RabbitMQ | 消息队列（AI 任务下发与结果回流、商品库同步） |
| Qdrant | 向量数据库（商品语义检索、用户偏好画像） |

### Qdrant 部署（二选一）

**方案 A：本地 Docker**

```bash
docker run -d --name qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v /root/qdrant/data:/qdrant/storage \
  --restart=always \
  qdrant/qdrant
```

`.env` 配置：

```
QDRANT_HOST=192.168.59.128
QDRANT_PORT=6333
QDRANT_API_KEY=
```

**方案 B：Qdrant Cloud（推荐）**

在 [https://cloud.qdrant.io](https://cloud.qdrant.io) 创建集群，获取 URL 和 API Key。

`.env` 配置：

```
QDRANT_HOST=https://xxx-xxx.aws.cloud.qdrant.io
QDRANT_PORT=6333
QDRANT_API_KEY=your-cloud-api-key
```

客户端会自动识别 `https://` 前缀并启用 SSL，无需额外配置。Qdrant Cloud 与本地部署功能完全一致，不影响其他组件。

## 与 Java 微服务的协作

- 配额与账务：Python 调用 Java user-service 的 `/credits/deduct|confirm|rollback` 管理 credits 预扣与确认
- 业务依赖：通过 `shared/java_client` 调用商品、购物车、订单、衣橱、尺码表等接口
- 消息解耦：AI 模特任务经 MQ 下发与回流；商品上下架经 MQ 同步到 Qdrant
- 实时推送：生成进度经 WebSocket 实时推送到前端，前端断连时以轮询兜底